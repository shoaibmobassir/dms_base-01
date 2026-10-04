import { expect, test, type APIRequestContext } from "@playwright/test";

// Calendar (plan 17, P3): a court date entered by one lawyer shows "unconfirmed" until a
// second lawyer confirms it; scopes; a private ICS subscription.
// The matter is named "E2E-TMP …" and removed (with its dates) by e2e/global-teardown.ts.

const ADMIN = "MEM-00011";

async function setup(request: APIRequestContext) {
  const users = ((await (await request.get("/api/admin/users", { headers: { "X-Member-Id": ADMIN } })).json()) as {
    items: { member_id: string; roles: string[] }[];
  }).items;
  const privileged = (u: { roles: string[] }) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance");
  const partner = users.find((u) => u.roles.includes("partner") && !privileged(u))!.member_id;
  const associate = users.find((u) => u.roles.includes("fee_earner") && !u.roles.includes("partner") && !privileged(u))!.member_id;
  const clients = (await (await request.get("/api/clients", { headers: { "X-Member-Id": partner } })).json()) as { items: { client_id: string; status?: string }[] };
  const made = await request.post("/api/matters", {
    headers: { "X-Member-Id": partner },
    data: { title: `E2E-TMP calendar ${Date.now().toString(36)}`, client_id: clients.items.find((c) => (c.status ?? "active") === "active")!.client_id,
      practice_area: "Disputes", team: [{ member_id: associate, role: "Associate" }] },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  return { partner, associate, matter: (await made.json()) as { matter_id: string; matter_code: string } };
}

async function as(browser: import("@playwright/test").Browser, member: string) {
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), member);
  return { ctx, page: await ctx.newPage() };
}

test("a court date needs a second lawyer to confirm it", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { partner, associate, matter } = await setup(request);
  const title = "Statement of defence due";
  const a = await as(browser, partner);
  try {
    await a.page.goto("/ui/calendar");
    await a.page.getByTestId("calendar-new-deadline").click();
    await a.page.getByTestId("calendar-create-title").fill(title);
    await a.page.getByTestId("calendar-create-matter").click();
    await a.page.getByTestId("calendar-create-matter-search").fill(matter.matter_code);
    await a.page.getByTestId("calendar-create-matter-option").filter({ hasText: matter.matter_code }).first().click();
    await a.page.getByTestId("calendar-create-save").click();
    await a.page.getByTestId("calendar-scope-mine").click();
    const row = a.page.getByTestId("deadlines-table").locator("tr", { hasText: title });
    await expect(row.getByTestId("badge-unconfirmed")).toBeVisible();
    // The person who entered it cannot confirm it.
    await row.click();
    await expect(a.page.getByTestId("calendar-item")).toBeVisible();
    await expect(a.page.getByTestId("calendar-confirm")).toHaveCount(0);
  } finally {
    await a.ctx.close();
  }

  const b = await as(browser, associate);
  try {
    await b.page.goto("/ui/calendar");
    await b.page.getByTestId("calendar-scope-matter").click();
    await b.page.getByTestId("calendar-matter").click();
    await b.page.getByTestId("calendar-matter-search").fill(matter.matter_code);
    await b.page.getByTestId("calendar-matter-option").filter({ hasText: matter.matter_code }).first().click();
    await b.page.getByTestId("deadlines-table").locator("tr", { hasText: title }).click();
    await b.page.getByTestId("calendar-confirm").click();
    await expect(b.page.getByTestId("deadlines-table").locator("tr", { hasText: title }).getByTestId("badge-unconfirmed")).toHaveCount(0);
  } finally {
    await b.ctx.close();
  }
});

test("subscribe: a private ICS link that works without signing in", async ({ browser, request }) => {
  const { partner } = await setup(request);
  const had = ((await (await request.get("/api/calendar/feed", { headers: { "X-Member-Id": partner } })).json()) as { active: boolean }).active;
  const a = await as(browser, partner);
  try {
    await a.page.goto("/ui/calendar");
    await a.page.getByTestId("calendar-subscribe").click();
    await a.page.getByTestId("calendar-feed-create").click();
    const url = await a.page.getByTestId("calendar-feed-url").inputValue();
    expect(url).toMatch(/\/api\/calendar-feed\/.+\.ics$/);
    const ics = await request.get(new URL(url).pathname); // no member header
    expect(ics.status()).toBe(200);
    expect(await ics.text()).toContain("BEGIN:VCALENDAR");
  } finally {
    await a.ctx.close();
    if (!had) await request.delete("/api/calendar/feed", { headers: { "X-Member-Id": partner } });
  }
});
