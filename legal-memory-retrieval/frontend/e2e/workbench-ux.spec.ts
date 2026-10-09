import { expect, test, type APIRequestContext, type Browser } from "@playwright/test";

// The workbench fixes from the product audit (docs/ui-roadmap/10): typing in the Word editor is never taken by a
// workbench shortcut, edits survive switching tabs and closing asks first, files are reachable on a phone, sharing
// from your own library, and the Documents page lists every place a document lives.
// Everything created is named "E2E-TMP …" and removed by e2e/global-teardown.ts.

const tag = () => `E2E-TMP ${Date.now().toString(36)}`;
const ADMIN = "MEM-00011";

async function people(request: APIRequestContext) {
  const res = await request.get("/api/admin/users", { headers: { "X-Member-Id": ADMIN } });
  const users = ((await res.json()) as { items: { member_id: string; roles: string[]; active?: boolean }[] }).items;
  const plain = users.filter((u) => u.active !== false && !u.roles.some((r) => r === "firm_admin" || r === "risk_compliance"));
  return { owner: plain[0].member_id, colleague: plain[1].member_id };
}

async function as(browser: Browser, member: string, viewport?: { width: number; height: number }) {
  const ctx = await browser.newContext(viewport ? { viewport } : {});
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), member);
  return { ctx, page: await ctx.newPage() };
}

const textFile = (name: string, body: string) => ({ name, mimeType: "text/plain", buffer: Buffer.from(body) });

async function upload(request: APIRequestContext, member: string, kind: string, id: string | undefined, name: string, body: string) {
  const multipart: Record<string, unknown> = { container_kind: kind, files: textFile(name, body) };
  if (id) multipart.container_id = id;
  const b = await (await request.post("/api/uploads/batches", { headers: { "X-Member-Id": member }, multipart: multipart as never })).json();
  return (await (await request.post(`/api/uploads/batches/${b.batch_id}/run`, { headers: { "X-Member-Id": member } })).json()).batch.files[0].document_id as string;
}

test("in the Word editor ⌘B stays bold, edits survive switching tabs, and closing with unsaved edits asks first", async ({ browser, request }) => {
  test.setTimeout(150_000);
  const M = "MEM-00001";
  const h = { "X-Member-Id": M };
  const docs = (await (await request.get("/api/documents?q=Employment%20Agreement%20-%20CTO&limit=5", { headers: h })).json()) as { items: { document_id: string; title: string }[] };
  const source = docs.items.find((d) => /\.docx$/i.test(d.title));
  test.skip(!source, "needs a Word document the member can read");
  const project = (await (await request.post("/api/projects", { headers: h, data: { title: `${tag()} Keep edits` } })).json()) as { project_id: string };
  const copy = (await (await request.post(`/api/workspaces/documents/${source!.document_id}/copy`, { headers: h, data: { kind: "project", id: project.project_id } })).json()) as { document_id: string };
  const other = await upload(request, M, "project", project.project_id, `other-${Date.now().toString(36)}.txt`, "E2E-TMP another document");
  const { ctx, page } = await as(browser, M);
  try {
    await page.goto(`/ui/work/project/${project.project_id}`);
    const row = (id: string) => page.locator(`[data-testid="explorer-document"][data-document-id="${id}"]`);
    await row(copy.document_id).hover();
    await row(copy.document_id).getByRole("button", { name: /actions/ }).click();
    await page.getByTestId("explorer-edit-word").click();
    await expect(page.getByText("Tracking: On")).toBeVisible({ timeout: 60_000 });
    await page.getByText("Mr Arvind Rao", { exact: false }).first().click();
    await page.keyboard.press("ControlOrMeta+b");
    // the side bar is still there: the shortcut went to the editor, not the workbench
    await expect(page.getByTestId("workbench-explorer")).toBeVisible();
    await page.keyboard.press("ControlOrMeta+b");
    await page.keyboard.type(" UXKEEP");
    await expect(page.getByTestId("tab-dirty")).toBeVisible({ timeout: 10_000 });
    // switch to another tab and back: the typing is still there
    await row(other).locator("button").first().dblclick();
    await page.getByTestId("workbench-tab").filter({ hasText: "(editing)" }).click();
    await expect(page.getByText("UXKEEP").first()).toBeVisible();
    // closing asks first
    await page.getByTestId("workbench-tab").filter({ hasText: "(editing)" }).hover();
    await page.getByRole("button", { name: /^Close .*Employment/ }).click();
    await expect(page.getByText(/without saving a version/)).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByTestId("workbench-tab").filter({ hasText: "(editing)" })).toBeVisible();
  } finally {
    await ctx.close();
    await request.delete(`/api/editor/documents/${copy.document_id}/draft-docx`, { headers: h }).catch(() => undefined);
  }
});

test("on a phone the files of a workspace are reachable", async ({ browser, request }) => {
  const { owner } = await people(request);
  const project = (await (await request.post("/api/projects", { headers: { "X-Member-Id": owner }, data: { title: `${tag()} Phone` } })).json()) as { project_id: string };
  const doc = await upload(request, owner, "project", project.project_id, `phone-${Date.now().toString(36)}.txt`, "E2E-TMP read on a phone");
  const { ctx, page } = await as(browser, owner, { width: 390, height: 844 });
  try {
    await page.goto(`/ui/work/project/${project.project_id}`);
    const row = page.locator(`[data-testid="explorer-document"][data-document-id="${doc}"]`);
    await expect(row).toBeVisible({ timeout: 30_000 });
    await row.locator("button").first().click();
    // opening a document shows it (the list steps aside)
    await expect(page.getByTestId("workbench-tab")).toHaveCount(1);
    await expect(page.getByTestId("side-panel-left")).toHaveCount(0);
  } finally {
    await ctx.close();
  }
});

test("a library document is shared from the explorer and shows under Shared with me", async ({ browser, request }) => {
  const { owner, colleague } = await people(request);
  const name = `E2E-TMP-shared-${Date.now().toString(36)}.txt`;
  const doc = await upload(request, owner, "library", undefined, name, "E2E-TMP a personal note to share");
  const { ctx, page } = await as(browser, owner);
  try {
    await page.goto("/ui/work/library/me");
    const row = page.locator(`[data-testid="explorer-document"][data-document-id="${doc}"]`);
    await expect(row).toBeVisible({ timeout: 30_000 });
    await row.click({ button: "right" });
    await page.getByTestId("explorer-share").click();
    await page.getByTestId("library-share-person").click();
    await page.getByTestId("library-share-person-menu").getByRole("option").first().click();
    const chosen = await page.getByTestId("library-share-person").innerText();
    await page.getByTestId("library-share-add").click();
    await expect(page.getByTestId("library-share")).toHaveCount(1);
    const shares = (await (await request.get(`/api/workspaces/documents/${doc}/shares`, { headers: { "X-Member-Id": owner } })).json()) as { shares: { principal_id: string; name: string }[] };
    expect(chosen).toContain(shares.shares[0].name);
    const sharedTo = shares.shares[0].principal_id;
    const theirs = (await (await request.get("/api/workspaces/shared-with-me", { headers: { "X-Member-Id": sharedTo } })).json()) as { documents: { document_id: string }[] };
    expect(theirs.documents.map((d) => d.document_id)).toContain(doc);
    expect(colleague).toBeTruthy();
  } finally {
    await ctx.close();
  }
});

test("Documents lists project and library files with where they live, and filters by it", async ({ browser, request }) => {
  const { owner } = await people(request);
  const word = `kestrel${Date.now().toString(36)}`;
  const doc = await upload(request, owner, "library", undefined, `E2E-TMP-${word}.txt`, `E2E-TMP ${word}`);
  const { ctx, page } = await as(browser, owner);
  try {
    await page.goto(`/ui/documents?home=library`);
    await page.getByTestId("documents-search").fill(word);
    const table = page.getByTestId("documents-table");
    await expect(table).toContainText(word, { timeout: 30_000 });
    await expect(table).toContainText("My library");
    await page.getByTestId("documents-home").getByRole("radio", { name: "Matters" }).click();
    await expect(page.getByTestId("documents-table")).toHaveCount(0);
    expect(doc).toBeTruthy();
  } finally {
    await ctx.close();
  }
});
