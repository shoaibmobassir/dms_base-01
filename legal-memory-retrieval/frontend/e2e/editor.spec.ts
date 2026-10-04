import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext } from "@playwright/test";

// Document editor (plan 16): edit a Word document in the browser, save it as a version,
// and see the lock from a second person. The sample document is created once in an open
// matter and reused; each run adds versions to it.

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = readFileSync(path.join(here, "fixtures", "editor-sample.docx"));
const TITLE = "E2E editor sample";

async function json<T>(request: APIRequestContext, url: string, member: string, init?: { method?: string; data?: unknown }): Promise<T> {
  const res = init?.method === "POST"
    ? await request.post(url, { headers: { "X-Member-Id": member }, data: init.data })
    : await request.get(url, { headers: { "X-Member-Id": member } });
  expect(res.ok(), `${url} → ${res.status()} ${await res.text()}`).toBeTruthy();
  return (await res.json()) as T;
}

/** An open matter with two non-admin team members, and the sample document in it (as .docx). */
async function setup(request: APIRequestContext) {
  const users = (await json<{ items: { member_id: string; roles: string[] }[] }>(request, "/api/admin/users", "MEM-00011")).items;
  const admins = new Set(users.filter((u) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance")).map((u) => u.member_id));
  const matters = (await json<{ items: { matter_id: string; restricted: boolean }[] }>(request, "/api/matters?limit=50", "MEM-00011")).items;
  for (const m of matters.filter((x) => !x.restricted)) {
    const detail = await json<{ team: { member_id: string }[] }>(request, `/api/matters/${m.matter_id}`, "MEM-00011");
    const staff = detail.team.map((t) => t.member_id).filter((id) => !admins.has(id));
    if (staff.length < 2) continue;
    const [editor, other] = staff;
    const found = await json<{ items: { document_id: string; title: string; matter_id: string }[] }>(
      request, `/api/documents?q=${encodeURIComponent(TITLE)}&limit=20`, editor);
    let doc = found.items.find((d) => d.title === TITLE && d.matter_id === m.matter_id)?.document_id;
    if (!doc) {
      doc = (await json<{ document_id: string }>(request, "/api/documents/ingest", editor, {
        method: "POST", data: { title: TITLE, matter_id: m.matter_id, body: "placeholder", document_type: "Agreement" },
      })).document_id;
    }
    // A lock left by an earlier run (a browser closed without releasing it) would block the upload.
    const held = await json<{ lock: { member_id: string } | null }>(request, `/api/editor/documents/${doc}`, editor);
    if (held.lock) await request.delete(`/api/editor/documents/${doc}/lock`, { headers: { "X-Member-Id": held.lock.member_id } });
    // Earlier runs' open comments would be carried to every new version: start without any.
    const existing = await json<{ threads: { comment_id: string; author_id: string }[] }>(
      request, `/api/editor/documents/${doc}/comments`, editor);
    for (const t of existing.threads)
      await request.delete(`/api/editor/documents/${doc}/comments/${t.comment_id}`, { headers: { "X-Member-Id": t.author_id } });
    // Always start from the fixture: upload it as the next version.
    const up = await request.post(`/api/editor/documents/${doc}/versions`, {
      headers: { "X-Member-Id": editor },
      multipart: { file: { name: "editor-sample.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: SAMPLE }, note: "e2e reset" },
    });
    expect(up.ok(), await up.text()).toBeTruthy();
    return { doc, editor, other };
  }
  throw new Error("no open matter with two non-admin team members");
}

test("edit a Word document in the browser and save it as a tracked version", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const { doc, editor, other } = await setup(request);
  const before = await json<{ version_number: number }>(request, `/api/editor/documents/${doc}`, editor);

  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  const page = await ctx.newPage();
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    await expect(page.getByTestId("editor-body")).toContainText("thirty (30) days");
    await expect(page.getByTestId("editor-body")).toHaveAttribute("contenteditable", "true");

    // A second person sees the lock and cannot edit.
    const ctx2 = await browser.newContext();
    await ctx2.addInitScript((id) => localStorage.setItem("precentis.persona", id), other);
    const page2 = await ctx2.newPage();
    await page2.goto(`/ui/documents/${doc}/edit`);
    await expect(page2.getByTestId("editor-locked")).toBeVisible();
    await expect(page2.getByTestId("editor-body")).toHaveAttribute("contenteditable", "false");
    await ctx2.close();

    // Edit the notice clause.
    const clause = page.getByTestId("editor-body").locator("p", { hasText: "thirty (30) days" });
    await clause.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" Notice may be given by email.");
    await expect(page.getByTestId("editor-changes")).toContainText("Changed");
    await expect(page.getByTestId("editor-draft-state")).toContainText("draft saved", { timeout: 10_000 });

    await page.getByTestId("editor-save").click();
    await page.getByTestId("editor-save-note").fill("Allow email notice");
    await page.getByTestId("editor-save-confirm").click();
    await expect(page).toHaveURL(new RegExp(`/ui/documents/${doc}\\?panel=versions`));
  } finally {
    await ctx.close();
  }

  const after = await json<{ version_number: number; paragraphs: { text: string }[]; has_revisions: boolean }>(
    request, `/api/editor/documents/${doc}`, editor);
  expect(after.version_number).toBe(before.version_number + 1);
  expect(after.has_revisions).toBe(true);
  expect(after.paragraphs.some((p) => p.text === "Either Party may terminate on thirty (30) days' written notice. Notice may be given by email.")).toBe(true);
  const history = await json<{ items: { action: string; member_id: string }[] }>(request, `/api/editor/documents/${doc}/history`, editor);
  // Newest first: the save, then leaving the editor releases the lock — and nothing re-locks it.
  expect(history.items.slice(0, 2).map((e) => e.action)).toEqual(["unlock", "edit.save"]);
  expect(history.items[1].member_id).toBe(editor);
});

test("exact view renders the Word file as pages", async ({ page, request }) => {
  const { doc, editor } = await setup(request);
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  await page.goto(`/ui/documents/${doc}/edit`);
  await page.getByTestId("editor-view-exact").click();
  await expect(page.getByTestId("editor-exact").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
});

test("comment on selected text in the exact view; a colleague replies; the thread is resolved", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor, other } = await setup(request);
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  const page = await ctx.newPage();
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    await page.getByTestId("editor-view-exact").click();
    const span = page.getByTestId("editor-exact").locator(".textLayer span", { hasText: "thirty" }).first();
    await expect(span).toBeAttached({ timeout: 30_000 });
    // Select the words in the text layer, as a mouse drag would.
    await span.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection()!;
      sel.removeAllRanges();
      sel.addRange(range);
      el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    });
    await page.getByTestId("comment-pill").click(); // select, then press Comment
    await expect(page.getByTestId("comment-composer")).toContainText("thirty");
    await page.getByTestId("comment-input").fill("Should this be sixty days?");
    await page.getByTestId("comment-submit").click();
    await expect(page.getByTestId("comment-thread")).toContainText("Should this be sixty days?");
    await expect(page.getByTestId("viewer-mark-badge")).toHaveText("1");
    await expect(page.getByTestId("viewer-mark").first()).toBeVisible();
  } finally {
    await ctx.close();
  }

  // A colleague sees the thread on the page and replies.
  const ctx2 = await browser.newContext();
  await ctx2.addInitScript((id) => localStorage.setItem("precentis.persona", id), other);
  const page2 = await ctx2.newPage();
  try {
    await page2.goto(`/ui/documents/${doc}/edit`);
    await page2.getByTestId("editor-view-exact").click();
    await page2.getByTestId("viewer-mark-badge").click();
    await page2.getByTestId("comment-thread").getByRole("button").first().click();
    await page2.getByTestId("comment-reply-input").fill("Yes — per the side letter.");
    await page2.getByTestId("comment-reply-submit").click();
    await expect(page2.getByTestId("comment-thread")).toContainText("Yes — per the side letter.");
    await page2.getByTestId("comment-resolve").click();
    await expect(page2.getByTestId("comment-list")).toContainText("No comments yet.");
    await page2.getByTestId("comments-show-resolved").check();
    await expect(page2.getByTestId("comment-thread")).toHaveAttribute("data-status", "resolved");
  } finally {
    await ctx2.close();
  }

  const list = await json<{ threads: { author_id: string; status: string; rects: unknown[]; replies: { author_id: string }[] }[] }>(
    request, `/api/editor/documents/${doc}/comments`, editor);
  const t = list.threads.at(-1)!;
  expect(t.author_id).toBe(editor);
  expect(t.status).toBe("resolved");
  expect(t.rects.length).toBeGreaterThan(0);
  expect(t.replies.map((r) => r.author_id)).toEqual([other]);
});

test("a second window of the same person takes over editing; the first stops", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const open = async () => {
    const ctx = await browser.newContext();
    await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
    const page = await ctx.newPage();
    await page.goto(`/ui/documents/${doc}/edit`);
    return { ctx, page };
  };
  const first = await open();
  const second = await open();
  try {
    await expect(first.page.getByTestId("editor-body")).toHaveAttribute("contenteditable", "true");
    await expect(second.page.getByTestId("editor-locked")).toContainText("another window");
    await second.page.getByTestId("editor-take-over").click();
    await expect(second.page.getByTestId("editor-body")).toHaveAttribute("contenteditable", "true");

    // The first window finds out on its next write and becomes read-only; nothing it types is saved.
    await first.page.getByTestId("editor-body").locator("p", { hasText: "thirty (30) days" }).click();
    await first.page.keyboard.press("End");
    await first.page.keyboard.type(" (stale window)");
    await expect(first.page.getByTestId("editor-locked")).toContainText("took over editing", { timeout: 10_000 });
    await expect(first.page.getByTestId("editor-body")).toHaveAttribute("contenteditable", "false");

    const model = await json<{ lock: { member_id: string } | null; draft: unknown }>(request, `/api/editor/documents/${doc}`, editor);
    expect(model.lock?.member_id).toBe(editor);
    expect(model.draft).toBeNull();
  } finally {
    await first.ctx.close();
    await second.ctx.close();
  }
});

test("an open comment follows the document to new versions, and shows where the text changed", async ({ page, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const h = { "X-Member-Id": editor };
  const quote = "within forty-five (45) days of invoice";
  const made = await request.post(`/api/editor/documents/${doc}/comments`, {
    headers: h, data: { body: "Is 45 days agreed?", page: 1, quote, rects: [{ x0: 0.2, y0: 0.4, x1: 0.7, y1: 0.43 }] },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  const cid = (await made.json()).comment_id as string;

  // v+1 with the same text: the thread is carried and found on the page.
  const up = await request.post(`/api/editor/documents/${doc}/versions`, {
    headers: h, multipart: { file: { name: "same.docx", mimeType: "application/octet-stream", buffer: SAMPLE } },
  });
  expect(up.ok(), await up.text()).toBeTruthy();
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  await page.goto(`/ui/documents/${doc}/edit`);
  await page.getByTestId("editor-view-exact").click();
  const thread = page.getByTestId("comment-thread").filter({ hasText: "Is 45 days agreed?" });
  await expect(thread.getByTestId("comment-carried")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("viewer-mark-badge")).toHaveCount(1);
  await expect(thread.getByTestId("comment-detached")).toHaveCount(0);

  // Another version rewrites that clause: the thread says so and opens its original version.
  const model = await json<{ base_version_id: string; paragraphs: { pid: number; text: string }[] }>(request, `/api/editor/documents/${doc}`, editor);
  const pid = model.paragraphs.find((p) => p.text.includes(quote))!.pid;
  const saved = await request.post(`/api/editor/documents/${doc}/save`, {
    headers: h, data: { base_version_id: model.base_version_id, ops: [{ op: "replace", pid, text: "The Client shall pay the Fees within thirty (30) days." }] },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.reload();
  await page.getByTestId("editor-view-exact").click();
  await expect(thread.getByTestId("comment-detached")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("viewer-mark-badge")).toHaveCount(0);
  await thread.getByTestId("comment-view-origin").click();
  await expect(page.getByTestId("exact-old-version")).toBeVisible();
  await expect(page.getByTestId("viewer-mark-badge")).toHaveCount(1, { timeout: 30_000 });

  await request.patch(`/api/editor/documents/${doc}/comments/${cid}`, { headers: h, data: { status: "resolved" } });
});

test("bold a clause and restyle a paragraph; the saved Word file carries the formatting", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  const page = await ctx.newPage();
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    const body = page.getByTestId("editor-body");
    await expect(body).toHaveAttribute("contenteditable", "true");
    await body.locator("p", { hasText: "forty-five" }).click({ clickCount: 3 });
    await page.getByTestId("editor-bold").click();
    await expect(page.getByTestId("editor-bold")).toHaveAttribute("aria-pressed", "true");
    await body.locator("p", { hasText: "thirty (30) days" }).click();
    await page.getByTestId("editor-style").selectOption("Heading 2");
    await expect(page.getByTestId("editor-changes")).toContainText("Formatted");
    await expect(page.getByTestId("editor-change-notes").first()).toBeVisible();
    await page.getByTestId("editor-save").click();
    await page.getByTestId("editor-save-note").fill("Emphasise the payment term");
    await page.getByTestId("editor-save-confirm").click();
    await expect(page).toHaveURL(new RegExp(`/ui/documents/${doc}\\?panel=versions`));
  } finally {
    await ctx.close();
  }
  const after = await json<{ has_revisions: boolean; paragraphs: { text: string; style: string; runs: { text: string; bold: boolean }[] }[] }>(
    request, `/api/editor/documents/${doc}`, editor);
  expect(after.has_revisions).toBe(true);
  const fees = after.paragraphs.find((p) => p.text.includes("forty-five"))!;
  expect(fees.runs.every((r) => r.bold)).toBe(true);
  expect(after.paragraphs.find((p) => p.text.includes("thirty (30) days"))!.style).toBe("Heading 2");
});

test("the document page shows the pages and comments without Edit; a comment is marked only when opened", async ({ browser, request }) => {
  test.setTimeout(120_000);
  const { doc, editor } = await setup(request);
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), editor);
  const page = await ctx.newPage();
  try {
    await page.goto(`/ui/documents/${doc}`);
    // The same rendered pages as the editor's exact view, and the comments, with no Edit button pressed.
    await expect(page.getByTestId("document-view-pages")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("editor-comments")).toBeVisible();
    const span = page.getByTestId("document-canvas").locator(".textLayer span", { hasText: "thirty" }).first();
    await expect(span).toBeAttached({ timeout: 30_000 });
    await span.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection()!;
      sel.removeAllRanges();
      sel.addRange(range);
      el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    });
    await page.getByTestId("comment-pill").click();
    await page.getByTestId("comment-input").fill("Check the notice period.");
    await page.getByTestId("comment-submit").click();
    await expect(page.getByTestId("comment-thread")).toContainText("Check the notice period.");
    await expect(page.getByTestId("viewer-mark").first()).toBeVisible(); // the new thread is the open one

    // After a reload nothing is highlighted until the comment is opened.
    await page.reload();
    await expect(page.getByTestId("viewer-mark-badge")).toHaveCount(1, { timeout: 30_000 });
    await expect(page.getByTestId("viewer-mark")).toHaveCount(0);
    await page.getByTestId("comment-thread").getByRole("button").first().click();
    await expect(page.getByTestId("viewer-mark").first()).toBeVisible();
  } finally {
    await ctx.close();
    const list = await json<{ threads: { comment_id: string; author_id: string }[] }>(request, `/api/editor/documents/${doc}/comments`, editor);
    for (const t of list.threads) await request.delete(`/api/editor/documents/${doc}/comments/${t.comment_id}`, { headers: { "X-Member-Id": t.author_id } });
  }
});
