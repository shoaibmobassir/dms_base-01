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

test("an uploaded reviewed file is imported clean, with every reviewer credited", async ({ request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  // Plan 21: a Word file with tracked changes becomes commits credited to its reviewers; nothing stays pending.
  const model = await json<{ pending_changes: number; has_revisions: boolean }>(request, `/api/editor/documents/${doc}`, editor);
  expect(model.pending_changes).toBe(0);
  expect(model.has_revisions).toBe(false);
  const who = await json<{ people: { name: string; external: boolean }[] }>(request, `/api/editor/documents/${doc}/contributors`, editor);
  const names = who.people.map((p) => p.name);
  for (const name of ["Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha"]) expect(names).toContain(name);
  expect(who.people.find((p) => p.name === "Trilegal")?.external).toBe(true);
  const commits = await json<{ items: { kind: string; message: string | null }[] }>(request, `/api/editor/documents/${doc}/commits`, editor);
  expect(commits.items.some((c) => c.kind === "import" || /tracked change/i.test(c.message ?? ""))).toBe(true);
});

test("an imported reviewed file opens in the editor clean, with nothing locked", async ({ browser, request }) => {
  test.setTimeout(90_000);
  const { doc, editor } = await setup(request);
  const { ctx, page } = await as(browser, editor);
  try {
    await page.goto(`/ui/documents/${doc}/edit`);
    const body = page.getByTestId("editor-body");
    await expect(body).toHaveAttribute("contenteditable", "true");
    await expect(page.getByTestId("editor-pending-chip")).toHaveCount(0);
    const para = body.locator("p", { hasText: "The Supplier shall deliver" });
    await expect(para).not.toHaveAttribute("data-locked-by", /./);
    await para.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" and on time");
    await expect(para).toContainText("and on time");
    await expect(page.getByTestId("editor-changes")).toContainText("Changed");
  } finally {
    await ctx.close();
  }
});
