import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext } from "@playwright/test";

// Word review (plan 18): a Word file reviewed by three people (Ravi Kalra, Trilegal, Kunal
// Lalit Kaistha — tracked changes and comments). See who changed what, accept one person's
// changes, find other reviewers' paragraphs locked in the editor, see Word comments, and get
// a Precentis reply back into the Word file.

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = readFileSync(path.join(here, "fixtures", "review-sample.docx"));
const TITLE = "E2E review sample";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

async function json<T>(request: APIRequestContext, url: string, member: string): Promise<T> {
  const res = await request.get(url, { headers: { "X-Member-Id": member } });
  expect(res.ok(), `${url} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

/** An open matter's non-admin team member, and the review sample reset to the fixture. */
async function setup(request: APIRequestContext) {
  const users = (await json<{ items: { member_id: string; roles: string[] }[] }>(request, "/api/admin/users", "MEM-00011")).items;
  const admins = new Set(users.filter((u) => u.roles.some((r) => r === "firm_admin" || r === "risk_compliance")).map((u) => u.member_id));
  const matters = (await json<{ items: { matter_id: string; restricted: boolean }[] }>(request, "/api/matters?limit=50", "MEM-00011")).items;
  for (const m of matters.filter((x) => !x.restricted)) {
    const detail = await json<{ team: { member_id: string }[] }>(request, `/api/matters/${m.matter_id}`, "MEM-00011");
    const editor = detail.team.map((t) => t.member_id).find((id) => !admins.has(id));
    if (!editor) continue;
    const found = await json<{ items: { document_id: string; title: string; matter_id: string }[] }>(
      request, `/api/documents?q=${encodeURIComponent(TITLE)}&limit=20`, editor);
    let doc = found.items.find((d) => d.title === TITLE && d.matter_id === m.matter_id)?.document_id;
    if (!doc) {
      doc = ((await (await request.post("/api/documents/ingest", {
        headers: { "X-Member-Id": editor },
        data: { title: TITLE, matter_id: m.matter_id, body: "placeholder", document_type: "Agreement" },
      })).json()) as { document_id: string }).document_id;
    }
    const held = await json<{ lock: { member_id: string } | null }>(request, `/api/editor/documents/${doc}`, editor);
    if (held.lock) await request.delete(`/api/editor/documents/${doc}/lock`, { headers: { "X-Member-Id": held.lock.member_id } });
    // Earlier runs' comments (and Word comments imported from earlier uploads) are cleared, then the
    // fixture comes in fresh.
    const existing = await json<{ threads: { comment_id: string; author_id: string | null }[] }>(
      request, `/api/editor/documents/${doc}/comments`, editor);
    for (const t of existing.threads) {
      await request.delete(`/api/editor/documents/${doc}/comments/${t.comment_id}`, { headers: { "X-Member-Id": t.author_id ?? "MEM-00011" } });
    }
    const up = await request.post(`/api/editor/documents/${doc}/versions`, {
      headers: { "X-Member-Id": editor },
      multipart: { file: { name: "review-sample.docx", mimeType: DOCX, buffer: SAMPLE }, note: "e2e reset" },
    });
    expect(up.ok(), await up.text()).toBeTruthy();
    return { doc, editor };
  }
  throw new Error("no open matter with a non-admin team member");
}

async function as(browser: import("@playwright/test").Browser, member: string) {
  const ctx = await browser.newContext();
  await ctx.addInitScript((id) => localStorage.setItem("precentis.persona", id), member);
  return { ctx, page: await ctx.newPage() };
}

test("see who changed what and accept one reviewer's changes", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const before = await json<{ version_number: number }>(request, `/api/editor/documents/${doc}`, editor);
  const { ctx, page } = await as(browser, editor);
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    await expect(page.getByTestId("editor-pending-chip")).toContainText("7 pending changes");
    await page.getByTestId("editor-view-review").click();
    const panel = page.getByTestId("review-panel");
    for (const name of ["Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"]) await expect(panel.getByTestId("review-people")).toContainText(name);
    await expect(panel.getByTestId("review-people")).toContainText("outside the firm");
    await expect(panel.getByTestId("review-change")).toHaveCount(6);
    await page.getByTestId("review-person-select").selectOption("Trilegal");
    await expect(panel.getByTestId("review-change")).toHaveCount(2);
    await page.getByTestId("review-accept-shown").click();
    await page.getByTestId("confirm-accept").click(); // several changes at once ask first
    // Stays in Review on the new version, without Trilegal's changes.
    await expect(page.getByTestId("review-panel")).toBeVisible();
    await expect(page.getByTestId("review-change").filter({ has: page.locator('[data-author="Trilegal"]') })).toHaveCount(0);
    await expect(page.getByTestId("review-change")).toHaveCount(4, { timeout: 15_000 });
  } finally {
    await ctx.close();
  }
  const after = await json<{ version_number: number; pending_people: string[] }>(request, `/api/editor/documents/${doc}`, editor);
  expect(after.version_number).toBe(before.version_number + 1);
  expect(after.pending_people).not.toContain("Trilegal");
  const history = await json<{ items: { action: string; member_id: string }[] }>(request, `/api/editor/documents/${doc}/history`, editor);
  expect(history.items.some((e) => e.action === "review.accept" && e.member_id === editor)).toBe(true);
});

test("paragraphs with other reviewers' pending changes are locked in the editor", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const { ctx, page } = await as(browser, editor);
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    const body = page.getByTestId("editor-body");
    await expect(body).toHaveAttribute("contenteditable", "true");
    const locked = body.locator("p", { hasText: "within 30 days" });
    await expect(locked).toHaveAttribute("data-locked-by", /Ravi Kalra/);
    await locked.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" and on time");
    await expect(page.getByTestId("editor-blocked")).toBeVisible();
    await expect(locked).not.toContainText("and on time");
    // A clean paragraph edits as usual.
    const clean = body.locator("p", { hasText: "Termination on notice." });
    await clean.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" Thirty days.");
    await expect(clean).toContainText("Thirty days.");
    await expect(page.getByTestId("editor-changes")).toContainText("Changed");
  } finally {
    await ctx.close();
  }
});

test("Word comments show in Precentis and replies go back into the Word file", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const { ctx, page } = await as(browser, editor);
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    await page.getByTestId("editor-view-exact").click();
    const thread = page.getByTestId("comment-thread").filter({ hasText: "Is 30 days agreed with the client?" });
    await expect(thread.getByTestId("comment-from-word")).toBeVisible({ timeout: 30_000 });
    await expect(thread).toContainText("Ravi Kalra");
    await expect(thread).toContainText("Yes — confirmed on the call.");
    await thread.getByRole("button").first().click();
    await page.getByTestId("comment-reply-input").fill("Noted in the engagement letter.");
    await page.getByTestId("comment-reply-submit").click();
    await expect(thread).toContainText("Noted in the engagement letter.");
  } finally {
    await ctx.close();
  }
  const file = await request.get(`/api/editor/documents/${doc}/download-with-comments`, { headers: { "X-Member-Id": editor } });
  expect(file.ok()).toBeTruthy();
  // The reply is inside the .docx (comments.xml is zipped: look for its text in the unzipped part via the API round trip).
  const back = await request.post(`/api/editor/documents/${doc}/versions`, {
    headers: { "X-Member-Id": editor },
    multipart: { file: { name: "from-word.docx", mimeType: DOCX, buffer: Buffer.from(await file.body()) } },
  });
  expect(back.ok()).toBeTruthy();
  const listed = await json<{ threads: { body: string; replies: { body: string }[] }[] }>(
    request, `/api/editor/documents/${doc}/comments`, editor);
  const replies = listed.threads.flatMap((t) => t.replies.map((r) => r.body));
  expect(replies.filter((b) => b === "Noted in the engagement letter.")).toHaveLength(1); // round-tripped, not duplicated
});
