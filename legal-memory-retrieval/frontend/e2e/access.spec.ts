import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Access model in the browser. People and the matter come from the API; the
// matter's access is restored at the end of each test.

type Wall = { matter_id: string; mode: string };

async function viewAs(page: Page, memberId: string) {
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), memberId);
}

async function getJson<T>(request: APIRequestContext, path: string, member: string): Promise<T> {
  const res = await request.get(path, { headers: { "X-Member-Id": member } });
  expect(res.ok(), `${path} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

/** An open matter with a non-admin lead, and a non-admin outsider. */
async function cast(request: APIRequestContext) {
  const admins = (await getJson<{ items: { member_id: string; roles: string[] }[] }>(request, "/api/admin/users", "MEM-00011")).items;
  const adminIds = new Set(admins.filter((u) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance")).map((u) => u.member_id));
  const matters = (await getJson<{ items: { matter_id: string; restricted: boolean }[] }>(request, "/api/matters?limit=50", "MEM-00011")).items;
  for (const m of matters.filter((x) => !x.restricted)) {
    const detail = await getJson<{ team: { member_id: string; role_on_matter: string | null }[] }>(request, `/api/matters/${m.matter_id}`, "MEM-00011");
    const lead = detail.team.find((t) => t.role_on_matter === "Lead" && !adminIds.has(t.member_id));
    const outsider = admins.find((u) => !adminIds.has(u.member_id) && !detail.team.some((t) => t.member_id === u.member_id));
    if (lead && outsider) return { matterId: m.matter_id, lead: lead.member_id, outsider: outsider.member_id, admin: [...adminIds][0] };
  }
  throw new Error("no open matter with a non-admin lead and outsider");
}

async function restoreOpen(request: APIRequestContext, matterId: string, member: string) {
  const access = await getJson<{ grants: { grant_id: string; reason: string }[] }>(request, `/api/access/matters/${matterId}`, member);
  for (const g of access.grants.filter((x) => x.reason.startsWith("Access request"))) {
    await request.delete(`/api/access/matters/${matterId}/grants/${g.grant_id}`, { headers: { "X-Member-Id": member } });
  }
  await request.put(`/api/access/matters/${matterId}`, { headers: { "X-Member-Id": member }, data: { mode: "open" } });
}

test("admin sees the Admin section; a fee earner does not", async ({ page, request }) => {
  const c = await cast(request);
  await viewAs(page, c.admin);
  await page.goto("/ui/admin");
  await expect(page.getByTestId("sidebar").getByRole("link", { name: "Admin", exact: true })).toBeVisible();
  await page.getByTestId("admin-tab-walls").click();
  await expect(page.getByTestId("admin-walls")).toBeVisible();

  const other = await page.context().newPage();
  await other.addInitScript((id) => localStorage.setItem("precentis.persona", id), c.outsider);
  await other.goto("/ui/");
  await expect(other.getByTestId("sidebar").getByRole("link", { name: "Home", exact: true })).toBeVisible();
  await expect(other.getByTestId("sidebar").getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
});

test("lead limits a matter to the team; an outsider requests and gets access", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const c = await cast(request);
  try {
    const leadPage = await (await browser.newContext()).newPage();
    await leadPage.addInitScript((id) => localStorage.setItem("precentis.persona", id), c.lead);
    await leadPage.goto(`/ui/matters/${c.matterId}`);
    await leadPage.getByTestId("matter-tab-access").click();
    await leadPage.getByTestId("access-mode-team").click();
    await expect(leadPage.getByTestId("access-mode-team")).toHaveClass(/border-wine/);

    const outsiderPage = await (await browser.newContext()).newPage();
    await outsiderPage.addInitScript((id) => localStorage.setItem("precentis.persona", id), c.outsider);
    await outsiderPage.goto(`/ui/matters/${c.matterId}`);
    await expect(outsiderPage.getByTestId("locked-matter")).toBeVisible();
    await outsiderPage.getByTestId("access-request-reason").fill("Covering the hearing next week");
    await outsiderPage.getByTestId("access-request-submit").click();
    await expect(outsiderPage.getByTestId("locked-matter")).toContainText("waiting for a decision");

    await leadPage.reload();
    await leadPage.getByTestId("matter-tab-access").click();
    await leadPage.getByTestId("access-requests").getByRole("button", { name: "Approve" }).click();
    await expect(leadPage.getByTestId("access-requests")).toHaveCount(0);

    await outsiderPage.goto(`/ui/matters/${c.matterId}`);
    await expect(outsiderPage.getByTestId("locked-matter")).toHaveCount(0);
    await expect(outsiderPage.getByTestId("matter-tab-overview")).toBeVisible();
  } finally {
    await restoreOpen(request, c.matterId, c.lead);
  }
});

test("walls overview matches the API", async ({ page, request }) => {
  const c = await cast(request);
  const walls = (await getJson<{ items: Wall[] }>(request, "/api/admin/walls", c.admin)).items;
  await viewAs(page, c.admin);
  await page.goto("/ui/admin");
  await page.getByTestId("admin-tab-walls").click();
  if (walls.length) await expect(page.getByTestId("admin-walls").locator("tbody tr")).toHaveCount(walls.length);
});
