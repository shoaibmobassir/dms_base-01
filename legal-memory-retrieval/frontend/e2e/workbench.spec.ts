import { expect, test, type APIRequestContext, type Browser } from "@playwright/test";

// Workbench (plan 22, W0–W1): projects anyone can start, single-copy documents shown in several workspaces,
// tabs, split, quick open, a layout that survives a reload, and a link that never widens access.
// Everything created is named "E2E-TMP …" and removed by e2e/global-teardown.ts.

const tag = () => `E2E-TMP ${Date.now().toString(36)}`;
const ADMIN = "MEM-00011";

async function people(request: APIRequestContext) {
  const res = await request.get("/api/admin/users", { headers: { "X-Member-Id": ADMIN } });
  const users = ((await res.json()) as { items: { member_id: string; roles: string[]; active?: boolean }[] }).items;
  const plain = users.filter((u) => u.active !== false && !u.roles.some((r) => r === "firm_admin" || r === "risk_compliance"));
  return { owner: plain[0].member_id, colleague: plain[1].member_id };
}

async function as(browser: Browser, member: string) {
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), member);
  return { ctx, page: await ctx.newPage() };
}

const textFile = (name: string, body: string) => ({ name, mimeType: "text/plain", buffer: Buffer.from(body) });

test("a project workspace: upload, open, split, quick open, and the layout comes back", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const { owner } = await people(request);
  const { ctx, page } = await as(browser, owner);
  try {
    await page.goto("/ui/projects");
    await page.getByTestId("new-project").click();
    const title = `${tag()} Workbench`;
    await page.getByTestId("project-title").fill(title);
    await page.getByTestId("project-create").click();
    await expect(page.getByTestId("workbench-title")).toHaveText(title);

    const stamp = Date.now().toString(36);
    await page.getByTestId("workspace-upload-input").setInputFiles([
      textFile(`alpha-${stamp}.txt`, `E2E-TMP ${stamp} alpha memo: the notice period is ninety days.`),
      textFile(`beta-${stamp}.txt`, `E2E-TMP ${stamp} beta memo: indemnity is capped at the fees paid.`),
    ]);
    const docs = page.getByTestId("explorer-document");
    await expect(docs).toHaveCount(2, { timeout: 60_000 });

    // single click: a preview tab; Alt-click: open to the side
    await docs.first().locator("button").first().click();
    await expect(page.getByTestId("workbench-tab")).toHaveCount(1);
    await docs.nth(1).locator("button").first().click({ modifiers: ["Alt"] });
    await expect(page.getByTestId("editor-group-1")).toBeVisible();
    await expect(page.getByTestId("editor-group-1").getByTestId("document-workspace")).toBeVisible();

    // quick open by name
    await page.keyboard.press("ControlOrMeta+p");
    await expect(page.getByTestId("quick-open")).toBeVisible();
    await page.keyboard.type(`beta-${stamp}`);
    await expect(page.getByTestId("quick-open").getByRole("option", { name: new RegExp(`beta-${stamp}`) })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("quick-open")).toBeHidden();

    // search inside the workspace's documents
    await page.getByTestId("activity-search").click();
    await page.getByTestId("workbench-search-input").fill("indemnity");
    await expect(page.getByTestId("workbench-search-hit")).toHaveCount(1);

    // the layout is saved per person and restored
    await page.waitForTimeout(1500);
    await page.reload();
    await expect(page.getByTestId("workbench-tab")).toHaveCount(2);
    await expect(page.getByTestId("editor-group-1")).toBeVisible();

    // commands by name
    await page.keyboard.press("ControlOrMeta+Shift+p");
    await expect(page.getByTestId("workbench-commands")).toBeVisible();
    await page.getByTestId("command-close-all").click();
    await expect(page.getByTestId("workbench-tab")).toHaveCount(0);
  } finally {
    await ctx.close();
  }
});

test("a linked document the viewer cannot read shows as restricted, never by name", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { owner, colleague } = await people(request);
  const h = { "X-Member-Id": owner };
  const mk = async (title: string) => (await (await request.post("/api/projects", { headers: h, data: { title } })).json()) as { project_id: string };
  const privateProject = await mk(`${tag()} Private`);
  const shared = await mk(`${tag()} Shared`);
  await request.put(`/api/projects/${shared.project_id}/members`, { headers: h, data: { principal_id: colleague, role: "viewer" } });
  const secret = `Secret-${Date.now().toString(36)}.txt`;
  const batch = await (
    await request.post("/api/uploads/batches", {
      headers: h,
      multipart: { container_kind: "project", container_id: privateProject.project_id, files: textFile(secret, "E2E-TMP privileged advice") },
    })
  ).json();
  const run = await (await request.post(`/api/uploads/batches/${batch.batch_id}/run`, { headers: h })).json();
  const docId = run.batch.files[0].document_id as string;
  expect((await request.post(`/api/workspaces/documents/${docId}/links`, { headers: h, data: { kind: "project", id: shared.project_id } })).status()).toBe(201);

  const { ctx, page } = await as(browser, colleague);
  try {
    await page.goto(`/ui/work/project/${shared.project_id}`);
    await expect(page.getByTestId("explorer-restricted")).toHaveCount(1);
    await expect(page.getByText(secret)).toHaveCount(0);
    await page.goto(`/ui/documents/${docId}`);
    await expect(page.getByText(secret)).toHaveCount(0);
  } finally {
    await ctx.close();
  }
});

test("add a document to a project from its page; it is the same document in both places", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { owner } = await people(request);
  const h = { "X-Member-Id": owner };
  const project = (await (await request.post("/api/projects", { headers: h, data: { title: `${tag()} Bundle` } })).json()) as { project_id: string };
  const lib = await (
    await request.post("/api/uploads/batches", {
      headers: h,
      multipart: { container_kind: "library", files: textFile(`note-${Date.now().toString(36)}.txt`, "E2E-TMP personal note") },
    })
  ).json();
  const docId = (await (await request.post(`/api/uploads/batches/${lib.batch_id}/run`, { headers: h })).json()).batch.files[0].document_id as string;

  const { ctx, page } = await as(browser, owner);
  try {
    await page.goto(`/ui/documents/${docId}`);
    await page.getByRole("button", { name: "Info", exact: true }).click();
    await page.getByTestId("document-add-to-workspace").click();
    await page.getByTestId("target-project").selectOption(project.project_id);
    await page.getByTestId("target-confirm").click();
    await expect(page.getByTestId("document-places")).toContainText("linked");
    await page.goto(`/ui/work/project/${project.project_id}`);
    await expect(page.locator(`[data-testid="explorer-document"][data-document-id="${docId}"]`)).toBeVisible();
  } finally {
    await ctx.close();
    // the library document is not an E2E-TMP project: remove it here
    await request.post(`/api/workspaces/documents/${docId}/move-home`, { headers: h, data: { kind: "project", id: project.project_id } });
  }
});

test("the Word editor tracks a change and saves it as a version credited to the signed-in person", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const M = "MEM-00001";
  const h = { "X-Member-Id": M };
  const docs = (await (await request.get("/api/documents?q=Employment%20Agreement%20-%20CTO&limit=5", { headers: h })).json()) as { items: { document_id: string; title: string }[] };
  const source = docs.items.find((d) => /\.docx$/i.test(d.title));
  test.skip(!source, "needs a Word document the member can read");
  const project = (await (await request.post("/api/projects", { headers: h, data: { title: `${tag()} Word editor` } })).json()) as { project_id: string };
  const copy = (await (await request.post(`/api/workspaces/documents/${source!.document_id}/copy`, { headers: h, data: { kind: "project", id: project.project_id } })).json()) as { document_id: string };
  const { ctx, page } = await as(browser, M);
  try {
    await page.goto(`/ui/documents/${copy.document_id}/write`);
    await expect(page.getByTestId("full-word-editor")).toBeVisible();
    await expect(page.getByText("Tracking: On")).toBeVisible({ timeout: 60_000 });
    await page.getByText("Mr Arvind Rao", { exact: false }).first().click();
    await page.waitForTimeout(500);
    await page.keyboard.type(" Added by the e2e test.");
    await page.getByTestId("full-editor-save").click();
    await page.getByTestId("full-editor-note").fill("e2e Word editor");
    await page.getByTestId("full-editor-confirm").click();
    await expect(page.getByTestId("full-editor-save-dialog")).toBeHidden({ timeout: 60_000 });
    const commits = (await (await request.get(`/api/editor/documents/${copy.document_id}/commits`, { headers: h })).json()) as { items: { version_number: number; kind: string; message: string }[] };
    expect(commits.items[0]).toMatchObject({ version_number: 2, kind: "editor", message: "e2e Word editor" });
    const text = await (await request.get(`/api/documents/${copy.document_id}/text`, { headers: h })).text();
    expect(text).toContain("Added by the e2e test");
  } finally {
    await ctx.close();
  }
});

test("drag a document onto a folder to file it, and onto another document to replace its content (confirmed)", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const { owner } = await people(request);
  const h = { "X-Member-Id": owner };
  const project = (await (await request.post("/api/projects", { headers: h, data: { title: `${tag()} Drag` } })).json()) as { project_id: string };
  const pid = project.project_id;
  const stamp = Date.now().toString(36);
  const upload = async (name: string, body: string) => {
    const b = await (await request.post("/api/uploads/batches", { headers: h, multipart: { container_kind: "project", container_id: pid, files: textFile(name, body) } })).json();
    return (await (await request.post(`/api/uploads/batches/${b.batch_id}/run`, { headers: h })).json()).batch.files[0].document_id as string;
  };
  const a = await upload(`source-${stamp}.txt`, `E2E-TMP ${stamp} the source text that should replace the target.`);
  const b = await upload(`target-${stamp}.txt`, `E2E-TMP ${stamp} the target text that will be replaced.`);
  await request.post(`/api/workspaces/project/${pid}/folders`, { headers: h, data: { path: "Archive" } });

  const { ctx, page } = await as(browser, owner);
  try {
    await page.goto(`/ui/work/project/${pid}`);
    await expect(page.getByTestId("explorer-document")).toHaveCount(2, { timeout: 30_000 });
    const row = (id: string) => page.locator(`[data-testid="explorer-document"][data-document-id="${id}"]`);
    // onto a folder: filed there
    await row(a).dragTo(page.getByTestId("explorer-folder").filter({ hasText: "Archive" }));
    await expect.poll(async () => ((await (await request.get(`/api/workspaces/documents/${a}`, { headers: h })).json()) as { places: { folder: string }[] }).places[0].folder).toBe("Archive");
    // onto another document: asks first, then a new version of the target; the source is unchanged
    await page.getByTestId("explorer-folder").filter({ hasText: "Archive" }).locator("button").first().click();
    await expect(row(a)).toBeVisible();
    await row(a).dragTo(row(b));
    await expect(page.getByText(/Replace the content of/)).toBeVisible();
    await page.getByRole("button", { name: "Replace content" }).click();
    await expect.poll(async () => ((await (await request.get(`/api/editor/documents/${b}/commits`, { headers: h })).json()) as { items: unknown[] }).items.length).toBe(2);
    const srcCommits = (await (await request.get(`/api/editor/documents/${a}/commits`, { headers: h })).json()) as { items: unknown[] };
    expect(srcCommits.items.length).toBe(1);
  } finally {
    await ctx.close();
  }
});

test("the Word editor keeps unsaved changes and offers them back after a reload", async ({ browser, request }) => {
  test.setTimeout(150_000);
  const M = "MEM-00001";
  const h = { "X-Member-Id": M };
  const docs = (await (await request.get("/api/documents?q=Employment%20Agreement%20-%20CTO&limit=5", { headers: h })).json()) as { items: { document_id: string; title: string }[] };
  const source = docs.items.find((d) => /\.docx$/i.test(d.title));
  test.skip(!source, "needs a Word document the member can read");
  const project = (await (await request.post("/api/projects", { headers: h, data: { title: `${tag()} Word draft` } })).json()) as { project_id: string };
  const copy = (await (await request.post(`/api/workspaces/documents/${source!.document_id}/copy`, { headers: h, data: { kind: "project", id: project.project_id } })).json()) as { document_id: string };
  const { ctx, page } = await as(browser, M);
  await page.addInitScript(() => { (window as unknown as { __autosaveMs: number }).__autosaveMs = 1500; });
  try {
    await page.goto(`/ui/documents/${copy.document_id}/write`);
    await expect(page.getByText("Tracking: On")).toBeVisible({ timeout: 60_000 });
    await page.getByText("Mr Arvind Rao", { exact: false }).first().click();
    await page.waitForTimeout(500);
    await page.keyboard.type(" Unsaved words for the draft.");
    await expect(page.getByTestId("full-editor-autosaved")).toBeVisible({ timeout: 30_000 });
    await page.reload();
    await expect(page.getByTestId("full-editor-draft")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("full-editor-restore").click();
    await expect(page.getByText("Unsaved words for the draft.")).toBeVisible({ timeout: 30_000 });
    // no version was made by any of this
    const commits = (await (await request.get(`/api/editor/documents/${copy.document_id}/commits`, { headers: h })).json()) as { items: unknown[] };
    expect(commits.items.length).toBe(1);
  } finally {
    await ctx.close();
  }
});
