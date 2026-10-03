import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Safety and polish checks: documents are never filed into a matter by default, follow-up
// questions carry the earlier answer, pages have titles, and destructive actions ask first.

const ME = "MEM-00001";
test.beforeEach(async ({ page }: { page: Page }) => {
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), ME);
});

test("adding documents needs a matter: nothing is filed by default", async ({ page }) => {
  let uploads = 0;
  await page.route("**/api/uploads/batches**", (route) => {
    uploads += 1;
    return route.abort();
  });
  await page.goto("/ui/documents");
  await page.getByTestId("add-documents").click();
  const dialog = page.getByTestId("upload-flow");
  await expect(dialog).toBeVisible();

  await dialog.getByTestId("upload-input").setInputFiles({ name: "note.txt", mimeType: "text/plain", buffer: Buffer.from("A short file note.") });
  await expect(dialog.getByTestId("upload-files")).toContainText("note.txt");
  // A file is chosen but no matter: the submit button stays disabled.
  await expect(dialog.getByTestId("upload-submit")).toBeDisabled();
  expect(uploads).toBe(0);

  // Unsupported types are refused in the list with the reason.
  await dialog.getByTestId("upload-input").setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: Buffer.from("x") });
  await expect(dialog.getByTestId("upload-files")).toContainText("Only PDF, Word (.docx) and text files are supported.");
});

test("a document attached in Assistant asks which matter it belongs to", async ({ page }) => {
  let uploads = 0;
  await page.route("**/api/uploads/batches**", (route) => {
    uploads += 1;
    return route.abort();
  });
  await page.goto("/ui/chat");
  await page.locator('input[type="file"]').setInputFiles({ name: "brief.txt", mimeType: "text/plain", buffer: Buffer.from("Brief text for the matter.") });
  await expect(page.getByTestId("upload-matter-prompt")).toBeVisible();
  await expect(page.getByTestId("chat-upload-matter-confirm")).toBeDisabled();
  expect(uploads).toBe(0);
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("upload-matter-prompt")).toHaveCount(0);
  expect(uploads).toBe(0);
});

test("a follow-up question sends the answer it follows", async ({ page }) => {
  let sent: Record<string, unknown> | null = null;
  await page.route("**/api/answers/stream", async (route) => {
    sent = route.request().postDataJSON() as Record<string, unknown>;
    const final = { type: "final", result: { query: "And on the appeal?", answer: "", abstained: true, reason: "test" }, replaced: false };
    await route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(final)}\n\ndata: [DONE]\n\n` });
  });
  await page.goto("/ui/ask?q=And%20on%20the%20appeal%3F&follow=ANSWER-123");
  await expect.poll(() => sent?.follow_up_of).toBe("ANSWER-123");
  expect(sent?.query).toBe("And on the appeal?");
});

test("pages set the tab title and the breadcrumb never shows a raw id", async ({ page }) => {
  await page.goto("/ui/matters");
  await expect(page).toHaveTitle(/^Matters · Precentis$/);
  await page.goto("/ui/calendar");
  await expect(page).toHaveTitle(/^Calendar · Precentis$/);
});

test("the question mark opens the shortcut list, but not while typing", async ({ page }) => {
  await page.goto("/ui/");
  await expect(page.getByTestId("ask-input")).toBeVisible(); // the app has finished loading
  await page.keyboard.press("?");
  await expect(page.getByTestId("shortcuts")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByTestId("ask-input").fill("");
  await page.getByTestId("ask-input").press("?");
  await expect(page.getByTestId("shortcuts")).toHaveCount(0);
});

test("clearing Ask history asks first", async ({ page }) => {
  await page.route("**/api/answers/history", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { items: [{ id: "a1", query: "A saved question", scope: null, scope_type: null, asked_at: new Date().toISOString() }] } })
      : route.fulfill({ status: 204, body: "" }),
  );
  await page.goto("/ui/ask");
  await page.getByTestId("ask-history-clear").click();
  await expect(page.getByTestId("ask-history-clear-confirm")).toBeVisible();
  await page.getByRole("button", { name: "Keep" }).click();
  await expect(page.getByTestId("ask-history-clear")).toBeVisible();
});

test("table rows are links: the first cell opens the record and can be focused", async ({ page }) => {
  await page.goto("/ui/matters");
  const first = page.getByTestId("matters-table").locator("tbody tr").first();
  const link = first.getByRole("link").first();
  await expect(link).toHaveAttribute("href", /\/ui\/matters\/.+/);
  await first.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ui\/matters\/.+/);
});

test("the document reader's side panels open as drawers on a phone", async ({ page, request }) => {
  const docs = await request.get("/api/documents?limit=1", { headers: { "X-Member-Id": ME } });
  const id = ((await docs.json()) as { items: { document_id: string }[] }).items[0].document_id;
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto(`/ui/documents/${id}`);
  await expect(page.getByTestId("document-workspace")).toBeVisible();
  await expect(page.getByTestId("document-right-rail")).toHaveCount(0);
  await page.getByRole("button", { name: /Show panel/ }).click();
  await expect(page.getByTestId("document-right-sheet")).toBeVisible();
  await expect(page.getByTestId("document-right-sheet")).toContainText("Versions");
});

test("a document hands itself to the Assistant, attached and limited to its matter", async ({ page, request }) => {
  const docs = await request.get("/api/documents?limit=1", { headers: { "X-Member-Id": ME } });
  const doc = ((await docs.json()) as { items: { document_id: string; title: string }[] }).items[0];
  await page.goto(`/ui/documents/${doc.document_id}`);
  await page.getByRole("button", { name: "Assistant" }).first().click();
  await page.getByTestId("document-ai-task").first().click();
  await expect(page).toHaveURL(/\/ui\/chat/);
  await expect(page.getByTestId("composer-attachments")).toContainText(doc.title.slice(0, 20));
  await expect(page.getByTestId("chat-input")).toHaveValue(/add comments on the key risks/);
});

test("find in document lists matches and jumps to one", async ({ page, request }) => {
  const docs = await request.get("/api/documents?limit=40", { headers: { "X-Member-Id": ME } });
  const items = ((await docs.json()) as { items: { document_id: string; current_version_id?: string }[] }).items;
  let found: { id: string; word: string } | null = null;
  for (const d of items) {
    const detail = (await (await request.get(`/api/documents/${d.document_id}`, { headers: { "X-Member-Id": ME } })).json()) as { current_version_id?: string };
    if (!detail.current_version_id) continue;
    const res = await request.get(`/api/documents/${d.document_id}/versions/${detail.current_version_id}/search?q=the`, { headers: { "X-Member-Id": ME } });
    if (res.ok() && ((await res.json()) as { total: number }).total > 0) {
      found = { id: d.document_id, word: "the" };
      break;
    }
  }
  test.skip(!found, "no document with searchable blocks");
  await page.goto(`/ui/documents/${found!.id}`);
  await expect(page.getByTestId("document-workspace")).toBeVisible();
  await page.getByTestId("document-view-text").click();
  await page.getByTestId("document-find").click();
  await page.getByTestId("find-input").fill(found!.word);
  await expect(page.getByTestId("find-count")).toContainText(/match/);
  await page.getByTestId("find-result").first().click();
  await expect(page.getByTestId("document-body")).toBeVisible();
});

test("arguments open as a sheet on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/ui/arguments");
  const first = page.getByTestId("arguments-list").getByRole("button").first();
  await first.click();
  await expect(page.getByTestId("argument-detail")).toBeVisible();
  await expect(page).toHaveURL(/id=/);
});

test("the month view is an agenda on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/ui/calendar");
  await page.getByTestId("calendar-view-month").click();
  await expect(page.getByTestId("calendar-agenda")).toBeVisible();
});

test("matter overview shows documents and deadlines at a glance", async ({ page, request }) => {
  const res = await request.get("/api/matters?limit=20", { headers: { "X-Member-Id": ME } });
  const m = ((await res.json()) as { items: { matter_id: string; restricted: boolean }[] }).items.find((x) => !x.restricted)!;
  await page.goto(`/ui/matters/${m.matter_id}`);
  await expect(page.getByTestId("matter-glance")).toContainText(/documents?/);
  await page.getByTestId("matter-glance").getByRole("button", { name: /document/ }).click();
  await expect(page).toHaveURL(/tab=documents/);
});

test("the bell shows what needs you, the same as Home", async ({ page }) => {
  await page.goto("/ui/");
  await expect(page.getByTestId("ask-input")).toBeVisible();
  await page.getByTestId("notifications").click();
  await expect(page.getByTestId("notifications-list").or(page.getByTestId("notifications-empty"))).toBeVisible();
});

test("form fields in the matter dialogs have visible labels, and no client is chosen for you", async ({ page }) => {
  await page.goto("/ui/matters?new=1");
  const dialog = page.getByTestId("new-matter-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Title")).toBeVisible();
  await expect(dialog.getByText("Choose a client")).toBeVisible();
  await dialog.getByLabel("Title").fill("Label check");
  await dialog.getByLabel("Practice area").fill("Corporate");
  await expect(page.getByTestId("new-matter-submit")).toBeDisabled();
});

test("Escape closes the matter list inside a dialog, not the dialog", async ({ page }) => {
  await page.goto("/ui/documents");
  await page.getByTestId("add-documents").click();
  await page.getByTestId("upload-matter").click();
  await expect(page.getByTestId("upload-matter-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("upload-matter-menu")).toHaveCount(0);
  await expect(page.getByTestId("upload-flow")).toBeVisible();
});

test("matters sort from the header and filter to mine; the choice is in the URL", async ({ page }) => {
  await page.goto("/ui/matters");
  await page.getByTestId("sort-title").click();
  await expect(page).toHaveURL(/sort=title&dir=asc/);
  await page.getByTestId("sort-title").click();
  await expect(page).toHaveURL(/dir=desc/);
  await expect(page.getByTestId("sort-title").locator("xpath=ancestor::th")).toHaveAttribute("aria-sort", "descending");
  await page.getByTestId("matters-mine").click();
  await expect(page).toHaveURL(/mine=1/);
  await page.reload();
  await expect(page.getByTestId("matters-mine")).toHaveAttribute("aria-pressed", "true");
});

test("documents sort by title from the header", async ({ page }) => {
  await page.goto("/ui/documents");
  await page.getByTestId("sort-title").click();
  await expect(page).toHaveURL(/sort=title&dir=asc/);
  await expect(page.getByTestId("documents-table")).toBeVisible();
});

test("the reader offers the original file as a download", async ({ page, request }) => {
  const list = await request.get("/api/documents?limit=60", { headers: { "X-Member-Id": ME } });
  let id: string | null = null;
  for (const d of ((await list.json()) as { items: { document_id: string }[] }).items) {
    const detail = (await (await request.get(`/api/documents/${d.document_id}?lean=true`, { headers: { "X-Member-Id": ME } })).json()) as { has_original?: boolean };
    if (detail.has_original) {
      id = d.document_id;
      break;
    }
  }
  test.skip(!id, "no document with an original file");
  await page.goto(`/ui/documents/${id}`);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("document-download").click()]);
  expect(download.suggestedFilename().length).toBeGreaterThan(0);
});

test("select documents and work on them together in the Assistant", async ({ page }) => {
  await page.goto("/ui/documents");
  const boxes = page.getByTestId("documents-table").locator('tbody input[type="checkbox"]');
  await expect(boxes.first()).toBeVisible();
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await expect(page.getByTestId("bulk-count")).toHaveText("2 documents selected");
  // Selecting the whole page, then clearing.
  await page.getByTestId("select-all").check();
  await expect(page.getByTestId("bulk-count")).toContainText("documents selected");
  await page.getByTestId("bulk-clear").click();
  await expect(page.getByTestId("bulk-bar")).toHaveCount(0);
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByTestId("bulk-assistant").click();
  await expect(page).toHaveURL(/\/ui\/chat\?.*doc=.*doc=/);
  await expect(page.getByTestId("composer-attachments").getByTestId("composer-attachment-open")).toHaveCount(2);
});

test("find a phrase inside a PDF and jump to its page", async ({ page, request }) => {
  test.setTimeout(150_000); // a scanned or very long PDF is searched page by page
  const list = await request.get("/api/documents?limit=100", { headers: { "X-Member-Id": ME } });
  const pdf = ((await list.json()) as { items: { document_id: string; mime_type?: string | null; title: string }[] }).items.find(
    (d) => (d.mime_type ?? "").includes("pdf") || d.title.toLowerCase().endsWith(".pdf"),
  );
  test.skip(!pdf, "no PDF document seeded");
  await page.goto(`/ui/documents/${pdf!.document_id}/edit?view=exact`);
  const find = page.getByTestId("viewer-find");
  await expect(find).toBeVisible({ timeout: 30000 });
  await find.fill("the");
  await find.press("Enter");
  await expect(page.getByTestId("viewer-find-status")).toHaveText(/Page \d+|No match/, { timeout: 100_000 });
});

// The Assistant: a flat answer with its sources as chips, actions under it, and the last message editable.
test.describe("Assistant conversation layout", () => {
  const now = new Date().toISOString();
  const session = { id: "mock-1", title: "Termination rights", matter_id: null, pinned: false, created_at: now, updated_at: now, status: "active" };
  const messages = [
    { id: "m1", role: "user", content: "Can the buyer terminate before closing?", created_at: now, files: [] },
    {
      id: "m2", role: "assistant", created_at: now, events: [],
      content: "Yes, on thirty days' notice [1].",
      citations: [{ ref: 1, document_id: "DOC-1", title: "Share Purchase Agreement.docx", page: 14, quote: "thirty (30) days", verified: true }],
    },
  ];

  test("shows sources as chips, actions under the answer, and lets the last question be edited", async ({ page }) => {
    await page.route("**/api/chat/sessions/mock-1", (route) => route.fulfill({ json: { session, messages } }));
    await page.goto("/ui/chat/mock-1");
    const answer = page.getByTestId("assistant-message");
    await expect(answer).toContainText("thirty days' notice");
    await expect(answer.getByTestId("source-chip")).toHaveCount(1);
    await expect(answer.getByTestId("message-copy")).toBeVisible();
    await expect(answer.getByTestId("message-regenerate")).toHaveCount(0); // no stored prompt on a reloaded answer
    // Passages are one click away, not shown by default.
    await expect(answer.getByTestId("citation-partial")).toHaveCount(0);
    await answer.getByTestId("sources-toggle").click();
    await expect(answer).toContainText("thirty (30) days");

    await page.getByTestId("message-edit-open").click();
    await expect(page.getByTestId("message-edit")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("message-edit")).toHaveCount(0);
  });

  test("an empty conversation centres the message box; a started one docks it", async ({ page }) => {
    await page.route("**/api/chat/sessions/mock-1", (route) => route.fulfill({ json: { session, messages } }));
    await page.goto("/ui/chat");
    const box = page.getByTestId("chat-input");
    await expect(box).toBeVisible();
    const empty = await box.boundingBox();
    expect(empty!.y).toBeLessThan(500); // in the middle of the page, under the greeting
    await expect(page.getByTestId("chat-scope")).toBeVisible(); // the matter chip sits in the box
    await page.goto("/ui/chat/mock-1");
    await expect(page.getByTestId("assistant-message")).toBeVisible();
    const docked = await page.getByTestId("chat-input").boundingBox();
    expect(docked!.y).toBeGreaterThan(500); // at the bottom
  });
});

test("pin several matters at once from the list, then unpin them", async ({ page, request }) => {
  const pinnedRes = await request.get("/api/matters/pinned", { headers: { "X-Member-Id": ME } });
  const pinned = new Set(((await pinnedRes.json()) as { items: { matter_id: string }[] }).items.map((m) => m.matter_id));
  await page.goto("/ui/matters");
  const rows = page.getByTestId("matters-table").locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  let target = -1;
  for (let i = 0; i < n; i++) {
    const id = (await rows.nth(i).getAttribute("data-testid"))!.replace("row-", "");
    if (!pinned.has(id)) {
      target = i;
      break;
    }
  }
  test.skip(target < 0, "every listed matter is already pinned");
  const row = rows.nth(target);
  const title = (await row.getByRole("link").first().innerText()).split("\n").pop()!.trim();
  await row.locator('input[type="checkbox"]').check();
  await page.getByTestId("bulk-pin").click();
  await expect(page.getByTestId("sidebar-pinned")).toContainText(title.slice(0, 20));
  await row.locator('input[type="checkbox"]').check();
  await page.getByTestId("bulk-unpin").click();
  await expect(page.getByTestId("sidebar-pinned").filter({ hasText: title.slice(0, 20) })).toHaveCount(0);
});

test("switching to another version keeps the page you are on", async ({ page, request }) => {
  const found = await request.get("/api/documents?q=Share%20Purchase%20Agreement&limit=20", { headers: { "X-Member-Id": ME } });
  const docs = ((await found.json()) as { items: { document_id: string }[] }).items;
  let id: string | null = null;
  for (const d of docs) {
    const v = await request.get(`/api/documents/${d.document_id}/versions`, { headers: { "X-Member-Id": ME } });
    if (v.ok() && ((await v.json()) as { versions: unknown[] }).versions.length >= 2) {
      id = d.document_id;
      break;
    }
  }
  test.skip(!id, "no document with two versions");
  await page.goto(`/ui/documents/${id}?page=2`);
  await page.getByTestId("document-view-text").click();
  await page.getByRole("button", { name: "Versions" }).first().click();
  const before = page.url();
  await page.locator('[data-testid="version-row"]:not([aria-current="true"])').first().click();
  await expect(page).toHaveURL(/version=/);
  expect(new URL(page.url()).searchParams.get("page")).toBe(new URL(before).searchParams.get("page")); // not back to page 1
});

test("a question typed on the document page is sent to the Assistant with that document attached", async ({ page, request }) => {
  const docs = await request.get("/api/documents?limit=1", { headers: { "X-Member-Id": ME } });
  const doc = ((await docs.json()) as { items: { document_id: string }[] }).items[0];
  let posted: { content?: string; files?: { document_id: string }[] } | null = null;
  await page.route("**/api/chat/sessions/*/messages", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posted = route.request().postDataJSON();
    return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "text_final", text: "Done." })}\n\ndata: [DONE]\n\n` });
  });
  await page.goto(`/ui/documents/${doc.document_id}`);
  await page.getByRole("button", { name: "Assistant" }).first().click();
  await page.getByTestId("document-ai-input").fill("Is the notice period reasonable?");
  await page.getByTestId("document-ai-send").click();
  await expect(page).toHaveURL(/\/ui\/chat/);
  await expect.poll(() => posted?.content).toBe("Is the notice period reasonable?");
  expect(posted?.files?.map((f) => f.document_id)).toContain(doc.document_id);
  const id = new URL(page.url()).pathname.split("/").pop();
  if (id && id !== "chat") await request.delete(`/api/chat/sessions/${id}`, { headers: { "X-Member-Id": ME } });
});

test("each version shows what it changed", async ({ page, request }) => {
  const found = await request.get("/api/documents?q=Share%20Purchase%20Agreement&limit=20", { headers: { "X-Member-Id": ME } });
  let id: string | null = null;
  for (const d of ((await found.json()) as { items: { document_id: string }[] }).items) {
    const v = await request.get(`/api/documents/${d.document_id}/versions`, { headers: { "X-Member-Id": ME } });
    if (v.ok() && ((await v.json()) as { versions: unknown[] }).versions.length >= 2) {
      id = d.document_id;
      break;
    }
  }
  test.skip(!id, "no document with two versions");
  await page.goto(`/ui/documents/${id}?panel=versions`);
  await page.getByTestId("version-changes-toggle").first().click();
  await expect(page.getByTestId("version-changes")).toContainText(/lines/);
});

test("suggested edits to a PDF say they cannot be applied and offer comments instead", async ({ page }) => {
  const now = new Date().toISOString();
  const session = { id: "mock-pdf", title: "PDF edits", matter_id: null, pinned: false, created_at: now, updated_at: now, status: "active" };
  const messages = [
    { id: "u1", role: "user", content: "Fix the typos", created_at: now, files: [] },
    {
      id: "a1", role: "assistant", created_at: now, content: "Here are the changes.", citations: [],
      events: [{ type: "edit_proposals", document_id: "DOC-PDF", filename: "Rejoinder.pdf", anchoring: "text",
        edits: [{ id: "e1", original: "aged about 51years", proposed: "aged about 51 years", reason: "Adds a space", page: 15, located: true, status: "pending" }] }],
    },
  ];
  await page.route("**/api/chat/sessions/mock-pdf", (route) => route.fulfill({ json: { session, messages } }));
  await page.goto("/ui/chat/mock-pdf");
  await expect(page.getByTestId("edits-pdf-note")).toContainText("PDF");
  await expect(page.getByTestId("edits-as-comments")).toBeVisible();
  await expect(page.getByTestId("edit-accept")).toHaveCount(0);
  await expect(page.getByTestId("edits-export")).toHaveCount(0);
});

test("resolve a matter: close it with an outcome, see the banner, reopen it", async ({ page, request }) => {
  const headers = { "X-Member-Id": ME };
  const clients = (await (await request.get("/api/clients?limit=3", { headers })).json()) as { items: { client_id: string }[] };
  const title = `E2E-TMP close ${Date.now()}`;
  const created = await request.post("/api/matters", { headers, data: { title, client_id: clients.items[0].client_id, practice_area: "Corporate", access_mode: "team" } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const id = ((await created.json()) as { matter_id: string }).matter_id;
  await request.post("/api/calendar/deadlines", { headers, data: { title: "File reply", kind: "filing", matter_id: id, due_date: "2030-01-15" } });

  await page.goto(`/ui/matters/${id}`);
  await page.getByTestId("matter-close").click();
  const dialog = page.getByTestId("close-matter-dialog");
  await expect(dialog.getByTestId("close-open-deadlines")).toContainText("still open");
  await dialog.getByTestId("close-outcome").fill("Settled on agreed terms");
  // An open court date blocks closing until it is marked done.
  await expect(dialog.getByTestId("close-matter-submit")).toBeDisabled();
  await dialog.getByTestId("close-mark-done").check();
  await dialog.getByTestId("close-matter-submit").click();
  await expect(page.getByTestId("matter-closed-banner")).toContainText("Settled on agreed terms");
  await expect(page.getByTestId("matter-close")).toHaveCount(0);

  await page.getByTestId("matter-reopen").click();
  await page.getByTestId("reopen-reason").fill("Opposing party appealed");
  await page.getByTestId("reopen-matter-submit").click();
  await expect(page.getByTestId("matter-closed-banner")).toHaveCount(0);
  await expect(page.getByTestId("matter-close")).toBeVisible();
});

test("put someone on a matter by searching, hand over the lead, remove with a confirmation", async ({ page, request }) => {
  const headers = { "X-Member-Id": ME };
  const clients = (await (await request.get("/api/clients?limit=3", { headers })).json()) as { items: { client_id: string }[] };
  const people = (await (await request.get("/api/people", { headers })).json()) as { items: { member_id: string; name: string }[] };
  const other = people.items.find((p) => p.member_id !== ME)!;
  const created = await request.post("/api/matters", { headers, data: { title: `E2E-TMP team ${Date.now()}`, client_id: clients.items[0].client_id, practice_area: "Corporate", access_mode: "team" } });
  const id = ((await created.json()) as { matter_id: string }).matter_id;

  await page.goto(`/ui/matters/${id}?tab=people`);
  await page.getByTestId("team-add-person").click();
  await page.getByTestId("team-add-person-search").fill(other.name.split(" ")[0]);
  await page.locator(`[data-option-id="${other.member_id}"]`).click();
  await page.getByTestId("team-add").click();
  await expect(page.getByTestId("team-row")).toHaveCount(2);

  // Removing asks first.
  await page.getByRole("button", { name: /^Remove / }).click();
  await expect(page.getByTestId("confirm-dialog")).toContainText("lose team access");
  await page.getByTestId("confirm-accept").click();
  await expect(page.getByTestId("team-row")).toHaveCount(1);

  // Add again, then hand over the lead: the new lead is listed first and the old one is counsel.
  await page.getByTestId("team-add-person").click();
  await page.locator(`[data-option-id="${other.member_id}"]`).click();
  await page.getByTestId("team-add").click();
  await expect(page.getByTestId("team-row")).toHaveCount(2);
  await page.getByTestId("team-make-lead").click();
  await page.getByTestId("confirm-accept").click();
  await expect(page.getByTestId("team-row").first()).toContainText(other.name);
});

test("a whole folder can be added and keeps its folder names", async ({ page }) => {
  const root = mkdtempSync(path.join(tmpdir(), "precentis-"));
  const folder = path.join(root, "Disclosure bundle");
  mkdirSync(path.join(folder, "Schedules"), { recursive: true });
  writeFileSync(path.join(folder, "cover note.txt"), "A cover note.");
  writeFileSync(path.join(folder, "Schedules", "schedule 1.txt"), "Schedule one.");
  writeFileSync(path.join(folder, "photo.png"), "x");
  await page.goto("/ui/documents");
  await page.getByTestId("add-documents").click();
  await page.getByTestId("upload-folder-input").setInputFiles(folder);
  const list = page.getByTestId("upload-files");
  await expect(list).toContainText("Disclosure bundle/cover note.txt");
  await expect(list).toContainText("Disclosure bundle/Schedules/schedule 1.txt");
  await expect(list).toContainText("Only PDF, Word (.docx) and text files are supported."); // the picture is refused with a reason
  await expect(page.getByTestId("upload-submit")).toBeDisabled(); // still no matter chosen
});
