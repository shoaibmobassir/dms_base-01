import { expect, test, type APIRequestContext } from "@playwright/test";

// Document privacy (plan 17, P1b): the author makes a document private in the UI; someone
// outside the share list can no longer find it or open its link; the author sees a lock.

const TOKEN = "Marrowlight";
const TITLE = "E2E privacy sample";

async function json<T>(request: APIRequestContext, url: string, member: string): Promise<T> {
  const res = await request.get(url, { headers: { "X-Member-Id": member } });
  expect(res.ok(), `${url} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

/** An open matter, a non-admin team member (the author) and a non-admin firm member outside the team. */
async function cast(request: APIRequestContext) {
  const users = (await json<{ items: { member_id: string; roles: string[] }[] }>(request, "/api/admin/users", "MEM-00011")).items;
  const admins = new Set(users.filter((u) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance")).map((u) => u.member_id));
  const matters = (await json<{ items: { matter_id: string; restricted: boolean }[] }>(request, "/api/matters?limit=50", "MEM-00011")).items;
  for (const m of matters.filter((x) => !x.restricted)) {
    const detail = await json<{ team: { member_id: string }[] }>(request, `/api/matters/${m.matter_id}`, "MEM-00011");
    const team = new Set(detail.team.map((t) => t.member_id));
    const author = [...team].find((id) => !admins.has(id));
    const outsider = users.map((u) => u.member_id).find((id) => !team.has(id) && !admins.has(id));
    if (author && outsider) return { matter: m.matter_id, author, outsider };
  }
  throw new Error("no open matter with a non-admin author and outsider");
}

test("make a document private: an outsider can no longer find or open it", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { matter, author, outsider } = await cast(request);
  // One sample document per matter, reused across runs; each run starts it back at "Matter".
  const found = await json<{ items: { document_id: string; title: string; matter_id: string }[] }>(
    request, `/api/documents?q=${encodeURIComponent(TITLE)}&limit=20`, author);
  let doc = found.items.find((d) => d.title === TITLE && d.matter_id === matter)?.document_id;
  if (!doc) {
    const made = await request.post("/api/documents/ingest", {
      headers: { "X-Member-Id": author },
      data: { title: TITLE, matter_id: matter, document_type: "Note",
        body: `Negotiation strategy for the ${TOKEN} deal: walk-away price and fallback positions.` },
    });
    expect(made.ok(), await made.text()).toBeTruthy();
    doc = (await made.json()).document_id as string;
  }
  await request.put(`/api/editor/documents/${doc}/privacy`, {
    headers: { "X-Member-Id": author }, data: { visibility: "matter", shares: [] },
  });

  try {
    // Before: the outsider can open it (the matter is firm-open).
    expect((await request.get(`/api/documents/${doc}`, { headers: { "X-Member-Id": outsider } })).status()).toBe(200);

    const ctx = await browser.newContext();
    await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), author);
    const page = await ctx.newPage();
    await page.goto(`/ui/documents/${doc}`);
    await expect(page.getByTestId("privacy-chip")).toHaveText(/Matter/);
    await page.getByTestId("privacy-chip").click();
    await page.getByTestId("privacy-private").check();
    await page.getByTestId("privacy-save").click();
    await expect(page.getByTestId("privacy-chip")).toHaveText(/Private/);
        await ctx.close();

    // After: the outsider's link and every listing are closed.
    const h = { "X-Member-Id": outsider };
    expect((await request.get(`/api/documents/${doc}`, { headers: h })).status()).toBe(404);
    expect((await request.get(`/api/documents/${doc}/text`, { headers: h })).status()).toBe(404);
    const listed = await json<{ items: { document_id: string }[] }>(request, `/api/documents?q=${encodeURIComponent(TITLE)}`, outsider);
    expect(listed.items.map((d) => d.document_id)).not.toContain(doc);
    const ctx2 = await browser.newContext();
    await ctx2.addInitScript((id) => localStorage.setItem("precentis.persona", id), outsider);
    const page2 = await ctx2.newPage();
    await page2.goto(`/ui/documents/${doc}`);
    await expect(page2.getByText("walk-away price")).toHaveCount(0);
    await ctx2.close();

    // The author still sees it, marked with a lock.
    const mine = await json<{ items: { document_id: string; privacy: string | null }[] }>(request, `/api/documents?q=${encodeURIComponent(TITLE)}`, author);
    expect(mine.items.find((d) => d.document_id === doc)?.privacy).toBe("private");
  } finally {
    await request.put(`/api/editor/documents/${doc}/privacy`, {
      headers: { "X-Member-Id": author }, data: { visibility: "matter", shares: [] },
    });
  }
});
