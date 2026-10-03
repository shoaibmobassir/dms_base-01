import { expect, test, type APIRequestContext } from "@playwright/test";

// Write layer (plan 17, P2): open a matter from the UI, staff it, add to its timeline;
// client intake with a conflict check; a colleague's page updates live.
// Everything created is named "E2E-TMP …" and removed by e2e/global-teardown.ts.

const ADMIN = "MEM-00011";
const tag = () => `E2E-TMP ${Date.now().toString(36)}`;

async function cast(request: APIRequestContext) {
  const res = await request.get("/api/admin/users", { headers: { "X-Member-Id": ADMIN } });
  const users = ((await res.json()) as { items: { member_id: string; roles: string[] }[] }).items;
  const privileged = (u: { roles: string[] }) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance");
  const partner = users.find((u) => u.roles.includes("partner") && !privileged(u))!.member_id;
  const associate = users.find((u) => u.roles.includes("fee_earner") && !u.roles.includes("partner") && !privileged(u))!.member_id;
  const clients = (await (await request.get("/api/clients", { headers: { "X-Member-Id": partner } })).json()) as {
    items: { client_id: string; status?: string }[];
  };
  const client = clients.items.find((c) => (c.status ?? "active") === "active")!.client_id;
  return { partner, associate, client };
}

async function as(browser: import("@playwright/test").Browser, member: string) {
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), member);
  return { ctx, page: await ctx.newPage() };
}

test("open a matter, staff it and add to its timeline", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { partner, associate } = await cast(request);
  const title = `${tag()} Series C financing`;
  const { ctx, page } = await as(browser, partner);
  try {
    await page.goto("/ui/matters");
    await page.getByTestId("matters-new").click();
    await page.getByTestId("new-matter-title").fill(title);
    await page.getByTestId("new-matter-client").click();
    await page.getByTestId("new-matter-client-option").first().click();
    await page.getByTestId("new-matter-practice").fill("Corporate");
    await page.getByTestId("new-matter-submit").click();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    const matterId = decodeURIComponent(page.url().split("/matters/")[1]);

    // Staff it.
    await page.getByTestId("matter-tab-people").click();
    await page.getByTestId("team-add-person").selectOption(associate);
    await page.getByTestId("team-add").click();
    await expect(page.getByTestId("team-row")).toHaveCount(2);

    // Timeline entry.
    await page.getByTestId("matter-tab-timeline").click();
    await page.getByTestId("timeline-add").click();
    await page.getByTestId("timeline-title").fill("Term sheet signed");
    await page.getByTestId("timeline-save").click();
    await expect(page.getByTestId("timeline-entry")).toContainText("Term sheet signed");

    // The associate now has it among their matters.
    const work = await (await request.get("/api/home/my-work", { headers: { "X-Member-Id": associate } })).json();
    expect((work.matters as { matter_id: string }[]).map((m) => m.matter_id)).toContain(matterId);
  } finally {
    await ctx.close();
  }
});

test("a colleague sees a new timeline entry appear without reloading", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { partner, associate, client } = await cast(request);
  const made = await request.post("/api/matters", {
    headers: { "X-Member-Id": partner },
    data: { title: `${tag()} live update`, client_id: client, practice_area: "Disputes", team: [{ member_id: associate, role: "Associate" }] },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  const matterId = (await made.json()).matter_id as string;
  const { ctx, page } = await as(browser, associate);
  try {
    await page.goto(`/ui/matters/${matterId}`);
    await page.getByTestId("matter-tab-timeline").click();
    await expect(page.getByText("Nothing on the timeline yet")).toBeVisible();
    await page.waitForTimeout(1500); // the live stream is connected
    const added = await request.post(`/api/matters/${matterId}/events`, {
      headers: { "X-Member-Id": partner }, data: { occurred_on: "2026-09-01", title: "Hearing listed for 12 October", kind: "hearing" },
    });
    expect(added.ok()).toBeTruthy();
    await expect(page.getByTestId("timeline-entry")).toContainText("Hearing listed for 12 October", { timeout: 15_000 });
  } finally {
    await ctx.close();
  }
});

test("client intake runs a conflict check first", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { partner } = await cast(request);
  const name = `${tag()} Quillonberry Holdings`;
  const { ctx, page } = await as(browser, partner);
  try {
    await page.goto("/ui/clients");
    await page.getByTestId("clients-new").click();
    await page.getByTestId("new-client-name").fill(name);
    await page.getByTestId("new-client-check").click();
    await expect(page.getByTestId("new-client-status")).toContainText("Clear");
    await page.getByTestId("new-client-create").click();
    await expect(page.getByTestId("new-client-dialog")).toHaveCount(0);
    const list = await (await request.get(`/api/clients?q=${encodeURIComponent(name)}`, { headers: { "X-Member-Id": partner } })).json();
    expect((list.items as { name: string; status: string }[]).find((c) => c.name === name)?.status).toBe("active");
  } finally {
    await ctx.close();
  }
});
