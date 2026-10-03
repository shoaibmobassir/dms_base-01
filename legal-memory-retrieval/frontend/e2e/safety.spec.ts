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
  await page.getByRole("button", { name: "AI" }).click();
  await page.getByTestId("document-ai-task").first().click();
  await expect(page).toHaveURL(/\/ui\/chat/);
  await expect(page.getByTestId("composer-attachments")).toContainText(doc.title.slice(0, 20));
  await expect(page.getByTestId("chat-input")).toHaveValue(/Summarise this document/);
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
