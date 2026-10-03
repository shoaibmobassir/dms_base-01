import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/** The calendar list's own window (today − 60 … today + 330, local dates), open items. */
async function calendarOpen(request: import("@playwright/test").APIRequestContext, member: string | undefined, scope = "firm") {
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const t = new Date();
  const from = iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 60));
  const to = iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 330));
  const res = await request.get(`/api/calendar?from=${from}&to=${to}&scope=${scope}`, { headers: member ? { "X-Member-Id": member } : {} });
  return ((await res.json()) as { items: { title: string; status: string; start: string }[] }).items.filter((i) => i.status === "open");
}


// Expected values come from the API (i.e. the seeded database) at test time.

type Matter = { matter_id: string; matter_code: string; title: string; client_id: string; restricted: boolean };

async function api<T>(request: APIRequestContext, path: string, member?: string): Promise<T> {
  const res = await request.get(path, { headers: member ? { "X-Member-Id": member } : {} });
  expect(res.ok(), `${path} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

async function viewAs(page: Page, memberId: string) {
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), memberId);
}

/** A restricted matter, a member inside its wall and one outside (from the DB). */
async function wall(request: APIRequestContext) {
  const all = await api<{ items: Matter[] }>(request, "/api/matters?limit=200"); // dev anonymous = unrestricted
  const people = (await api<{ items: { member_id: string }[] }>(request, "/api/people")).items.map((p) => p.member_id);
  for (const m of all.items.filter((x) => x.restricted)) {
    const detail = await api<{ matter: { acl_members: string[] } }>(request, `/api/matters/${m.matter_id}`);
    const inside = detail.matter.acl_members;
    const outsider = people.find((p) => !inside.includes(p));
    if (inside.length && outsider) return { matter: m, insider: inside[0], outsider };
  }
  throw new Error("No restricted matter — run scripts/seed_demo.py");
}

test("shell shows the firm from the database and only wired sections", async ({ page, request }) => {
  const firm = await api<{ name: string }>(request, "/api/system/firm");
  await page.goto("/ui/");
  await expect(page.getByTestId("firm-identity")).toContainText(firm.name);

  const nav = page.getByTestId("sidebar");
  for (const label of ["Home", "Assistant", "Ask the Firm", "Matters", "Documents", "Calendar", "Arguments", "Clients", "People", "Settings"]) {
    await expect(nav.getByRole("link", { name: label, exact: true })).toBeVisible();
  }
  await expect(nav).toContainText("Precentis");
  for (const removed of ["Projects", "Activity", "Strategy", "Precedents", "Due Diligence", "Knowledge Gaps", "Audit", "Teams", "Deadlines"]) {
    await expect(nav.getByRole("link", { name: removed, exact: true })).toHaveCount(0);
  }
});

test("home stats match the API for the current member", async ({ page, request }) => {
  const people = (await api<{ items: { member_id: string; name: string }[] }>(request, "/api/people")).items;
  const me = people[0];
  await viewAs(page, me.member_id);
  const stats = await api<{ counts: { matters: number; open_deadlines: number } }>(request, "/api/home/stats", me.member_id);

  await page.goto("/ui/");
  const panel = page.getByTestId("home-stats");
  await expect(panel).toContainText(`${stats.counts.matters}matters in your access scope`);
  await expect(panel).toContainText(`${stats.counts.open_deadlines}open court deadlines`);
  await expect(page.getByTestId("user-menu")).toContainText(me.name);
});

test("matters list and search are served by the API", async ({ page, request }) => {
  const people = (await api<{ items: { member_id: string }[] }>(request, "/api/people")).items;
  await viewAs(page, people[0].member_id);
  const first = (await api<{ items: Matter[] }>(request, "/api/matters?limit=50", people[0].member_id)).items[0];

  await page.goto("/ui/matters");
  await expect(page.getByTestId("matters-table")).toContainText(first.title);

  await page.getByTestId("matters-search").fill(first.matter_code);
  await expect(page.getByTestId(`row-${first.matter_id}`)).toBeVisible();
  await expect(page.getByTestId("matters-table").locator("tbody tr")).toHaveCount(1);
});

test("ethical wall: a restricted matter is hidden from outsiders and visible to its team", async ({ page, request }) => {
  const { matter, insider, outsider } = await wall(request);

  await viewAs(page, outsider);
  await page.goto("/ui/matters");
  await page.getByTestId("matters-search").fill(matter.matter_code);
  await expect(page.getByText("No matters found")).toBeVisible();
  await page.goto(`/ui/matters/${matter.matter_id}`);
  await expect(page.getByText("outside your access scope")).toBeVisible();

  // Switch persona through the UI: the same page re-queries as the new member
  // (no reload — addInitScript would re-apply the outsider on navigation).
  await page.getByTestId("user-menu").click();
  await page.getByTestId(`persona-${insider}`).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(matter.title);
  await expect(page.getByText("Restricted").first()).toBeVisible();
});

test("matter detail tabs render API data", async ({ page, request }) => {
  const { matter, insider } = await wall(request);
  await viewAs(page, insider);
  const timeline = (await api<{ timeline: { event: string }[] }>(request, `/api/matters/${matter.matter_id}/timeline`, insider)).timeline;
  const deadlines = (await api<{ items: { title: string }[] }>(request, `/api/tasks?status=all&matter_id=${matter.matter_id}`, insider)).items;

  await page.goto(`/ui/matters/${matter.matter_id}`);
  await page.getByTestId("matter-tab-timeline").click();
  await expect(page.getByTestId("matter-timeline")).toContainText(timeline[0].event);
  await page.getByTestId("matter-tab-deadlines").click();
  await expect(page.getByText(deadlines[0].title)).toBeVisible();
  await page.getByTestId("matter-tab-documents").click();
  await expect(page.getByTestId("matter-documents").locator("tbody tr").first()).toBeVisible();
});

test("document opens with its indexed text", async ({ page, request }) => {
  const { matter, insider } = await wall(request);
  await viewAs(page, insider);
  const doc = (await api<{ items: { document_id: string; title: string }[] }>(request, `/api/documents?matter_id=${matter.matter_id}&limit=1`, insider)).items[0];
  const text = await api<{ text: string }>(request, `/api/documents/${doc.document_id}/text`, insider);

  await page.goto(`/ui/documents/${doc.document_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(doc.title);
  await expect(page.getByTestId("document-body")).toContainText(text.text.slice(0, 40).trim());
});

test("deadlines and client memory come from seeded tables", async ({ page, request }) => {
  const { matter, insider } = await wall(request);
  await viewAs(page, insider);
  const open = await calendarOpen(request, insider);
  await page.goto("/ui/deadlines"); // redirects to /calendar
  await expect(page).toHaveURL(/\/ui\/calendar$/);
  await expect(page.getByTestId("deadlines-table").locator("tbody tr")).toHaveCount(open.length);

  const client = await api<{ notes: { text: string }[] }>(request, `/api/clients/${matter.client_id}`, insider);
  await page.goto(`/ui/clients/${matter.client_id}`);
  await expect(page.getByTestId("client-notes")).toContainText(client.notes[0].text);
});

test("command palette searches the API", async ({ page, request }) => {
  const people = (await api<{ items: { member_id: string }[] }>(request, "/api/people")).items;
  await viewAs(page, people[0].member_id);
  const m = (await api<{ items: Matter[] }>(request, "/api/matters?status=Open&limit=1", people[0].member_id)).items[0];

  await page.goto("/ui/");
  await page.getByTestId("open-command").click();
  await page.getByTestId("command-input").fill(m.matter_code);
  await page.getByRole("option", { name: new RegExp(m.title.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).click();
  await expect(page).toHaveURL(new RegExp(`/ui/matters/${m.matter_id}$`));
});

test("chat opens with suggestions from the member's open matters", async ({ page, request }) => {
  const { insider } = await wall(request);
  await viewAs(page, insider);
  const suggestions = (await api<{ suggestions: string[] }>(request, "/api/chat/suggestions", insider)).suggestions;

  await page.goto("/ui/chat");
  await expect(page.getByTestId("chat-title")).toHaveText("New conversation");
  if (suggestions.length) await expect(page.getByTestId("chat-suggestion").first()).toContainText(suggestions[0]);
  await expect(page.getByTestId("chat-input")).toBeVisible();
});

test("history docks beside the thread, is searchable, pins, renames and deletes", async ({ page, request }) => {
  const { insider, matter } = await wall(request);
  await viewAs(page, insider);
  const headers = { "X-Member-Id": insider };
  const created = await request.post("/api/chat/sessions", { headers, data: {} });
  expect(created.ok()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };
  const title = `History check ${Date.now()}`;
  await request.patch(`/api/chat/sessions/${id}`, { headers, data: { title } });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/chat/${id}`);
  await expect(page.getByTestId("chat-title")).toHaveText(title);
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(title); // not the UUID

  await page.getByTestId("chat-history-toggle").click();
  const pane = page.getByTestId("chat-history");
  await expect(pane).toBeVisible();
  const row = pane.locator('[data-testid="chat-session-row"]:has([aria-current="page"])');
  await expect(row).toContainText(title);

  // The docked pane stays open across a reload.
  await page.reload();
  await expect(page.getByTestId("chat-history")).toBeVisible();

  await page.getByTestId("chat-history-search").fill("no conversation is called this");
  await expect(pane).toContainText("No conversations match.");
  await page.getByTestId("chat-history-search").fill(title);
  await expect(row).toBeVisible();

  // Pin: the row moves to a Pinned group and the Pinned filter appears.
  await row.getByTestId("chat-session-menu").click();
  await page.getByRole("menuitem", { name: "Pin to top" }).click();
  await expect(pane).toContainText("Pinned");
  await page.getByTestId("chat-history-search").fill("");
  await page.getByTestId("chat-history-filter-pinned").click();
  await expect(pane.getByTestId("chat-session-row")).toHaveCount(1);
  await page.getByTestId("chat-history-filter-all").click();

  // Limit the conversation to one matter; the choice is saved with it.
  await page.getByTestId("chat-scope").click();
  await page.getByTestId("chat-scope-search").fill(matter.matter_code);
  await page.getByTestId("chat-scope-option").filter({ hasText: matter.title }).first().click();
  await expect(page.getByTestId("chat-scope")).toContainText(matter.matter_code);
  await page.reload();
  await expect(page.getByTestId("chat-scope")).toContainText(matter.matter_code);
  await expect(pane.locator('[data-testid="chat-session-row"]:has([aria-current="page"])')).toContainText(matter.matter_code);

  const renamed = `${title} (renamed)`;
  await row.getByTestId("chat-session-menu").click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await pane.getByLabel("Conversation title").fill(renamed);
  await pane.getByLabel("Conversation title").press("Enter");
  await expect(page.getByTestId("chat-title")).toHaveText(renamed);

  await row.getByTestId("chat-session-menu").click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await pane.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/chat$/);

  await page.getByRole("button", { name: "Hide history" }).click();
  await expect(page.getByTestId("chat-history")).toBeHidden();
});

test("starter cards fill the message box and the mode menu explains each mode", async ({ page }) => {
  await page.goto("/ui/chat");
  const card = page.getByTestId("chat-starter").first();
  const prompt = (await card.getAttribute("title"))!; // the starter chip carries its prompt as its title
  await card.click();
  await expect(page.getByTestId("chat-input")).toHaveValue(prompt);
  await expect(page).toHaveURL(/\/ui\/chat$/); // nothing was sent

  await page.getByTestId("chat-mode").click();
  await expect(page.getByTestId("chat-mode-review")).toContainText("Table of issues");
  await page.getByTestId("chat-mode-review").click();
  await expect(page.getByTestId("chat-mode")).toContainText("Risk review");
  await expect(page.getByTestId("chat-review-note")).toBeVisible();
});

test("a multi-document review renders as a table whose cells open the quote", async ({ page }) => {
  const table = {
    type: "review_table", mode: "full", questions: ["Governing law?"],
    stats: { model_calls: 2, cached: 0, answered: 1, verified_quotes: 1, errors: 0 }, timings: { total_ms: 2300 },
    rows: [
      { document_id: "DOC-E9058749C1", title: "Share Purchase Agreement.docx", matter_code: "CORP/BLR/0901/2026",
        cells: [{ question: "Governing law?", answer: "Laws of India", quote: "governed by the laws of India", page: 12, verified: true, not_found: false }] },
      { document_id: "DOC-06D46C4AD1", title: "Board Resolution.docx", matter_code: "CORP/BLR/0901/2026",
        cells: [{ question: "Governing law?", answer: "", quote: "", page: null, verified: false, not_found: true }] },
    ],
  };
  await page.route("**/api/chat/sessions/*/messages", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const events = [table, { type: "text_final", text: "One of the two documents states a governing law." }];
    return route.fulfill({
      contentType: "text/event-stream",
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") + "data: [DONE]\n\n",
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/ui/chat");
  await page.getByTestId("chat-input").fill("What is the governing law of each agreement?");
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("review-table")).toContainText("Reviewed 2 documents");
  await expect(page.getByTestId("review-row")).toHaveCount(2);
  await expect(page.getByTestId("review-table")).toContainText("Not found");
  await page.getByLabel("Only documents with an answer").check();
  await expect(page.getByTestId("review-row")).toHaveCount(1);
  await page.getByTestId("review-cell").first().click();
  await expect(page.getByText("governed by the laws of India").first()).toBeVisible();
});

test("document-wide edits page through and offer accept / reject all", async ({ page }) => {
  const edits = Array.from({ length: 45 }, (_, i) => ({
    id: `e${i}`, op: "replace", pid: i, original: `${i + 1}.1 The Supplier shall comply.`,
    proposed: `${i + 1}.1 The Vendor shall comply.`, reason: "", page: i + 1, located: true, status: "pending",
  }));
  const group = { type: "edit_proposals", document_id: "DOC-E9058749C1", filename: "Share Purchase Agreement.docx",
    anchoring: "paragraph", source: "docx", instruction: "Rename Supplier to Vendor", edits };
  await page.route("**/api/chat/sessions/*/messages", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const events = [group, { type: "text_final", text: "45 edits proposed." }];
    return route.fulfill({ contentType: "text/event-stream",
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") + "data: [DONE]\n\n" });
  });
  await page.goto("/ui/chat");
  await page.getByTestId("chat-input").fill("Rename Supplier to Vendor everywhere");
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("edit-proposals")).toContainText("(45)");
  await expect(page.getByTestId("edit-card")).toHaveCount(20);
  await page.getByTestId("edits-more").click();
  await expect(page.getByTestId("edit-card")).toHaveCount(40);
  await expect(page.getByTestId("edits-accept-all")).toBeVisible();
  await expect(page.getByTestId("edits-reject-all")).toBeVisible();
});

// ── document viewer beside the chat ───────────────────────────────────────────

test("attached PDF opens beside the chat with page and zoom controls", async ({ page, request }) => {
  const docs = await api<{ items: { document_id: string; title: string }[] }>(request, "/api/documents?q=.pdf&limit=20");
  let pdf: { document_id: string; title: string } | undefined;
  for (const d of docs.items) {
    const res = await request.get(`/api/documents/${d.document_id}/render`);
    if (res.ok() && (res.headers()["content-type"] ?? "").includes("pdf")) {
      pdf = d;
      break;
    }
  }
  test.skip(!pdf, "no PDF original in the seeded corpus");

  await page.goto("/ui/chat");
  await page.getByTestId("composer-add").click();
  await page.getByRole("menuitem", { name: "Choose firm documents" }).click();
  await page.getByTestId("document-picker-search").fill(pdf!.document_id);
  await page.getByTestId("document-picker-item").filter({ hasText: pdf!.document_id }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("composer-attachments")).toContainText(pdf!.title);

  await page.getByTestId("composer-attachment-open").click();
  const viewer = page.getByTestId("document-viewer");
  await expect(viewer).toBeVisible();
  await expect(page.getByTestId("viewer-page-count")).toHaveText(/\/ \d+/);
  const pages = Number((await page.getByTestId("viewer-page-count").innerText()).replace(/\D/g, ""));
  const first = page.locator('[data-testid="viewer-page"][data-page="1"]');
  const box = (await first.boundingBox())!;
  expect(box.height / box.width).toBeGreaterThan(1.2); // portrait page keeps its shape

  if (pages > 1) {
    await page.getByTestId("viewer-next").click();
    await expect(page.getByTestId("viewer-page-input")).toHaveValue("2");
    await page.getByTestId("viewer-page-input").fill(String(pages));
    await page.getByTestId("viewer-page-input").press("Enter");
    await expect(page.getByTestId("viewer-page-input")).toHaveValue(String(pages));
  }
  const before = await page.getByTestId("viewer-zoom").innerText();
  await page.getByTestId("viewer-zoom-in").click();
  await expect(page.getByTestId("viewer-zoom")).not.toHaveText(before);
  await page.getByTestId("viewer-fit-width").click();
  await expect(page.getByTestId("viewer-zoom")).toHaveText(before);
});

// These call the configured LLM; opt in with E2E_LLM=1.
test.describe("chat with the language model", () => {
  test.skip(!process.env.E2E_LLM, "set E2E_LLM=1 to exercise the language model");

  test("answers with cited sources, auto-titles, and deletes", async ({ page, request }) => {
    test.setTimeout(180_000);
    const { matter, insider } = await wall(request);
    await viewAs(page, insider);

    await page.goto("/ui/chat");
    await page.getByTestId("chat-input").fill(`What relief was sought in ${matter.title}?`);
    await page.getByTestId("chat-send").click();
    await expect(page).toHaveURL(/\/ui\/chat\/[0-9a-f-]+$/);
    const answer = page.getByTestId("assistant-message").last();
    await expect(answer.getByTestId("chat-sources")).toBeVisible({ timeout: 150_000 });
    await expect(page.getByTestId("chat-title")).not.toHaveText(/Untitled|New conversation/);

    // A citation opens the source beside the chat, on its page, with the words marked.
    await answer.getByTestId("chat-citation-1").first().click();
    await expect(page.getByTestId("citation-document-panel")).toBeVisible();
    await expect(
      page.locator(".viewer-highlight, [data-testid=viewer-ocr-highlight], [data-testid=citation-highlight]").first(),
    ).toBeVisible({ timeout: 30_000 });

    // Delete from the history pane (row menu, then confirm), then the URL resets to a new chat.
    await page.getByTestId("chat-history-toggle").click();
    const row = page.locator('[data-testid="chat-session-row"]:has([aria-current="page"])');
    await row.getByTestId("chat-session-menu").click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page.getByTestId("chat-sessions").getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page).toHaveURL(/\/ui\/chat$/);
  });

  test("a conversation limited to a matter cites only that matter's documents", async ({ request }) => {
    test.setTimeout(180_000);
    const member = "MEM-00001";
    const headers = { "X-Member-Id": member };
    const matters = await api<{ items: (Matter & { document_count: number })[] }>(request, "/api/matters?limit=200", member);
    const matter = matters.items.find((m) => !m.restricted && m.document_count >= 3)!;
    const created = await request.post("/api/chat/sessions", { headers, data: { matter_id: matter.matter_id } });
    const { id } = (await created.json()) as { id: string };
    try {
      const res = await request.post(`/api/chat/sessions/${id}/ask`, {
        headers,
        data: { content: "Summarise the key documents and what each one says.", mode: "cite" },
        timeout: 170_000,
      });
      expect(res.ok()).toBeTruthy();
      const { citations } = (await res.json()) as { citations: { document_id?: string }[] };
      const ids = [...new Set(citations.map((c) => c.document_id).filter(Boolean))] as string[];
      expect(ids.length).toBeGreaterThan(0);
      for (const docId of ids) {
        const doc = await api<{ matter_id: string }>(request, `/api/documents/${docId}`, member);
        expect(doc.matter_id, `${docId} is outside ${matter.matter_code}`).toBe(matter.matter_id);
      }
    } finally {
      await request.delete(`/api/chat/sessions/${id}`, { headers });
    }
  });

  test("stop keeps the conversation and marks the answer stopped", async ({ page, request }) => {
    test.setTimeout(120_000);
    const { matter, insider } = await wall(request);
    await viewAs(page, insider);

    await page.goto("/ui/chat");
    await page.getByTestId("chat-input").fill(`Summarise every filing in ${matter.title}.`);
    await page.getByTestId("chat-send").click();
    await page.getByTestId("chat-stop").click();
    await expect(page.getByText("Stopped — the partial answer above has been saved.")).toBeVisible();
    await expect(page.getByTestId("chat-send")).toBeVisible();

    const id = page.url().split("/").pop()!;
    await request.delete(`/api/chat/sessions/${id}`, { headers: { "X-Member-Id": insider } });
  });
});

// ── P0 foundations ────────────────────────────────────────────────────────────

test("theme: dark mode applies and survives a reload", async ({ page }) => {
  await page.goto("/ui/");
  await page.getByTestId("theme-menu").click();
  await page.getByTestId("theme-dark").click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/); // applied before first paint
  await page.getByTestId("theme-menu").click();
  await page.getByTestId("theme-light").click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("calendar month view and /teams redirect", async ({ page, request }) => {
  const { insider } = await wall(request);
  await viewAs(page, insider);
  const now = new Date();
  const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const inMonth = (await calendarOpen(request, insider)).filter((i) => i.start.startsWith(thisMonth));
  await page.goto("/ui/calendar");
  await page.getByTestId("calendar-view-month").click();
  if (inMonth.length) await expect(page.getByTestId("calendar-month")).toContainText(inMonth[0].title);
  else await expect(page.getByTestId("calendar-month")).toBeVisible();

  await page.goto("/ui/teams");
  await expect(page).toHaveURL(/\/ui\/settings#teams$/);
  await expect(page.getByTestId("teams-table")).toBeVisible();
});

test("pinning a matter puts it in the sidebar", async ({ page, request }) => {
  const people = (await api<{ items: { member_id: string }[] }>(request, "/api/people")).items;
  const me = people[0].member_id;
  await viewAs(page, me);
  const m = (await api<{ items: Matter[] }>(request, "/api/matters?status=Open&limit=1", me)).items[0];
  await request.delete(`/api/matters/${m.matter_id}/pin`, { headers: { "X-Member-Id": me } });

  await page.goto(`/ui/matters/${m.matter_id}`);
  await page.getByTestId("matter-pin").click();
  await expect(page.getByTestId("sidebar-pinned")).toContainText(m.title);
  await page.getByTestId("matter-pin").click(); // unpin
  await expect(page.getByTestId("sidebar-pinned")).toHaveCount(0);
});

test("sidebar can be resized by dragging its edge", async ({ page }) => {
  await page.goto("/ui/");
  const aside = page.getByTestId("sidebar").locator("xpath=..");
  const before = (await aside.boundingBox())!.width;
  const handle = (await page.getByTestId("sidebar-resize").boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + 200);
  await page.mouse.down();
  await page.mouse.move(handle.x + 60, handle.y + 200, { steps: 5 });
  await page.mouse.up();
  const after = (await aside.boundingBox())!.width;
  expect(after).toBeGreaterThan(before + 30);
  await page.getByTestId("sidebar-resize").dblclick(); // reset
});

test("mobile shows the bottom navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ui/");
  const bottom = page.getByTestId("bottom-nav");
  await expect(bottom).toBeVisible();
  await bottom.getByRole("link", { name: "Matters" }).click();
  await expect(page).toHaveURL(/\/ui\/matters$/);
});

test("Acme sample matter was ingested through the upload pipeline", async ({ page, request }) => {
  const acme = (await api<{ items: Matter[] }>(request, "/api/matters?q=Acme&limit=5", "MEM-00001")).items[0];
  expect(acme, "run scripts/seed_acme.py").toBeTruthy();
  await viewAs(page, "MEM-00001");
  await page.goto(`/ui/matters/${acme.matter_id}`);
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(acme.title);
  await page.getByTestId("matter-tab-documents").click();
  await expect(page.getByTestId("matter-documents")).toContainText("Share Purchase Agreement.docx");
  await page.getByTestId("matter-documents").getByText("Share Purchase Agreement.docx").click();
  // Current version = v2. The body is shown page by page; the amended clause is on page 2.
  await expect(page.getByTestId("document-body")).not.toBeEmpty();
  await page.getByTestId("document-page-input").fill("2");
  await page.getByTestId("document-page-input").press("Enter");
  await expect(page.getByTestId("document-body")).toContainText("fifteen (15) days");
  // Two versions in the history, the open one being the current v2.
  await expect(page.getByTestId("document-version-chip")).toContainText("2");
});
