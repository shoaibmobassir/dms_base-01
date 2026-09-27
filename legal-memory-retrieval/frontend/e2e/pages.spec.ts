import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Work pages after the second design pass: plain headings with counts, one date
// format, new columns and filters, and the links between Ask, Assistant and matters.
// Expected values come from the API at test time.

type Matter = { matter_id: string; matter_code: string; title: string; restricted: boolean };

async function api<T>(request: APIRequestContext, path: string, member?: string): Promise<T> {
  const res = await request.get(path, { headers: member ? { "X-Member-Id": member } : {} });
  expect(res.ok(), `${path} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

async function viewAs(page: Page, memberId: string) {
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), memberId);
}

const ISO_DATE = /\b\d{4}-\d{2}-\d{2}\b/;
// Pages and API calls run as the same person so counts agree with the access scope.
const ME = "MEM-00001";

test.beforeEach(async ({ page }) => viewAs(page, ME));

test("matters list: plain heading with a count, lead and next deadline, readable dates", async ({ page, request }) => {
  const { total } = await api<{ total: number }>(request, "/api/matters?limit=1", ME);
  await page.goto("/ui/matters");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Matters");
  await expect(page.getByTestId("page-count")).toHaveText(`${total} matters`);
  const table = page.getByTestId("matters-table");
  await expect(table.getByRole("columnheader", { name: "Lead" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Next deadline" })).toBeVisible();
  await expect(table).not.toContainText(ISO_DATE);
});

test("documents list: type and matter filters, file kinds instead of 'Uploaded'", async ({ page, request }) => {
  const { document_types } = await api<{ document_types: { value: string; n: number }[] }>(request, "/api/documents/facets", ME);
  const kind = document_types.find((t) => t.value !== "Uploaded" && t.n < 50) ?? document_types[0];
  await page.goto("/ui/documents");
  const table = page.getByTestId("documents-table");
  await expect(table).toBeVisible();
  await expect(table.locator("td", { hasText: /^Uploaded$/ })).toHaveCount(0);
  await expect(table).not.toContainText(ISO_DATE);

  await page.getByTestId("documents-type").selectOption(kind.value);
  await expect(page.getByTestId("page-count")).toHaveText(`${kind.n} ${kind.n === 1 ? "document" : "documents"}`);

  const matters = await api<{ items: Matter[] }>(request, "/api/matters?limit=200", ME);
  const m = matters.items.find((x) => !x.restricted)!;
  const docs = await api<{ total: number }>(request, `/api/documents?matter_id=${m.matter_id}&limit=1`, ME);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page.getByTestId("documents-matter").selectOption(m.matter_id);
  await expect(page.getByTestId("page-count")).toHaveText(`${docs.total} ${docs.total === 1 ? "document" : "documents"}`);
});

test("arguments: kind filter and a detail pane with forum, lead and documents", async ({ page, request }) => {
  const { kinds } = await api<{ kinds: Record<string, number> }>(request, "/api/knowledge/arguments?limit=1", ME);
  test.skip(!kinds.disputes, "no dispute arguments seeded");
  await page.goto("/ui/arguments");
  await expect(page.getByTestId("arguments-kind-disputes")).toContainText(String(kinds.disputes));
  await page.getByTestId("arguments-kind-disputes").click();
  await expect(page.getByTestId("page-count")).toHaveText(`${kinds.disputes} records`);
  const list = page.getByTestId("arguments-list");
  await expect(list.getByRole("button")).toHaveCount(kinds.disputes);
  const detail = page.getByTestId("argument-detail");
  await expect(detail).toContainText("Forum");
  await expect(detail).toContainText("Led by");
  await expect(page.getByTestId("argument-documents")).toBeVisible();
});

test("clients show open matters and relationship lead; people filter by practice", async ({ page, request }) => {
  await page.goto("/ui/clients");
  const clients = page.getByTestId("clients-table");
  await expect(clients.getByRole("columnheader", { name: "Open matters" })).toBeVisible();
  await expect(clients.getByRole("columnheader", { name: "Relationship lead" })).toBeVisible();

  const people = (await api<{ items: { practice_areas: string[]; current_matters: number }[] }>(request, "/api/people", ME)).items;
  const practice = people.flatMap((p) => p.practice_areas).sort()[0];
  const expected = people.filter((p) => p.practice_areas.includes(practice)).length;
  await page.goto("/ui/people");
  await expect(page.getByTestId("people-table").getByRole("columnheader", { name: "Open matters" })).toBeVisible();
  await page.getByTestId(`people-practice-${practice}`).click();
  await expect(page.getByTestId("people-table").locator("tbody tr")).toHaveCount(expected);
});

test("calendar: readable dates and a 'Mine only' filter", async ({ page, request }) => {
  const deadlines = (await api<{ items: { owner_member_id: string | null }[] }>(request, "/api/tasks?status=open&limit=100")).items;
  const owner = deadlines.find((d) => d.owner_member_id)?.owner_member_id;
  test.skip(!owner, "no owned deadlines seeded");
  const mine = deadlines.filter((d) => d.owner_member_id === owner).length;
  await viewAs(page, owner!);
  await page.goto("/ui/calendar");
  const table = page.getByTestId("deadlines-table");
  await expect(table).toBeVisible();
  await expect(table).not.toContainText(ISO_DATE);
  await page.getByTestId("calendar-mine").check();
  await expect(table.locator("tbody tr")).toHaveCount(mine);
});

test("home: one way to ask, deadlines first, recent questions and conversations", async ({ page }) => {
  await page.goto("/ui/");
  await expect(page.getByTestId("home-ask")).toHaveCount(0);
  await expect(page.getByTestId("home-assistant")).toBeVisible();
  await expect(page.getByTestId("home-recent-questions")).toBeVisible();
  await expect(page.getByTestId("home-recent-conversations")).toBeVisible();
  const deadlines = await page.getByTestId("home-deadlines").boundingBox();
  const matters = await page.getByTestId("home-matters").boundingBox();
  if (deadlines && matters) expect(deadlines.y).toBeLessThan(matters.y);
});

test("a matter opens the Assistant limited to it, with starters from its documents, without an empty conversation", async ({ page, request }) => {
  const matters = await api<{ items: (Matter & { document_count: number })[] }>(request, "/api/matters?limit=200", ME);
  const m = matters.items.find((x) => !x.restricted && x.document_count > 0)!;
  await page.goto(`/ui/matters/${m.matter_id}`);
  const before = (await api<unknown[]>(request, "/api/chat/sessions?limit=100", ME)).length;
  await page.getByTestId("matter-assistant").click();
  await expect(page).toHaveURL(/\/ui\/chat$/); // nothing is created until the first message
  await expect(page.getByTestId("chat-scope")).toContainText(m.matter_code);
  await expect(page.getByTestId("chat-starters-label")).toHaveText(`Start on ${m.matter_code}`);
  // A document starter puts the prompt in the box and attaches that document.
  await page.getByTestId("chat-starter").filter({ hasText: "Review" }).first().click();
  await expect(page.getByTestId("chat-input")).toHaveValue(/^Review /);
  await expect(page.getByTestId("composer-attachments")).toBeVisible();
  expect((await api<unknown[]>(request, "/api/chat/sessions?limit=100", ME)).length).toBe(before);
});

test("command palette offers a new Assistant conversation", async ({ page }) => {
  await page.goto("/ui/");
  await page.getByTestId("open-command").click();
  await page.getByTestId("command-new-conversation").click();
  await expect(page).toHaveURL(/\/ui\/chat$/);
});

test("settings keeps the development persona list folded away", async ({ page }) => {
  await page.goto("/ui/settings");
  await page.getByTestId("settings-theme-light").waitFor();
  await page.getByText(/Associate|Partner/).first().waitFor();
  const personas = page.getByTestId("settings-personas");
  test.skip((await personas.count()) === 0, "sign-in is on: no persona switcher");
  await expect(personas.locator("button").first()).toBeHidden();
  await personas.locator("summary").click();
  await expect(personas.locator("button").first()).toBeVisible();
});
