import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

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
  for (const label of ["Home", "Chat", "Matters", "Documents", "Calendar", "Arguments", "Clients", "People", "Settings"]) {
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
  const open = (await api<{ items: { title: string; matter_code: string }[] }>(request, "/api/tasks?status=open", insider)).items;
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

    // Delete through the conversation drawer (confirm step), then the URL resets to a new chat.
    await page.getByRole("button", { name: "Conversations" }).click();
    const row = page.getByTestId("chat-sessions").locator("div.group").first();
    await row.hover();
    await row.getByRole("button", { name: "Delete" }).click();
    await row.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page).toHaveURL(/\/ui\/chat$/);
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
  const open = (await api<{ items: { title: string }[] }>(request, "/api/tasks?status=open", insider)).items;
  await page.goto("/ui/calendar");
  await page.getByTestId("calendar-view-month").click();
  await expect(page.getByTestId("calendar-month")).toContainText(open[0].title);

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
  await expect(page.getByTestId("document-body")).toContainText("fifteen (15) days"); // current version = v2
  await expect(page.getByTestId("doc-history")).toContainText("(2)");
});
