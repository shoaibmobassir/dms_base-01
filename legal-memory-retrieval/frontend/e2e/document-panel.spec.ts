import { expect, test, type APIRequestContext } from "@playwright/test";

// The document beside an answer (Assistant and Ask the Firm share it): the reader moves page by page, sees which
// page they are on, and in the Text view can jump to a page too (plan 21, G-E). The answer is a fixed stream so the
// test does not depend on a language model.

const ME = "MEM-00011";

async function multiPageDocument(request: APIRequestContext): Promise<{ id: string; title: string } | null> {
  const res = await request.get("/api/documents?limit=60", { headers: { "X-Member-Id": ME } });
  const items = ((await res.json()) as { items: { document_id: string; title: string }[] }).items;
  for (const d of items.filter((x) => x.title.toLowerCase().endsWith(".pdf"))) {
    const detail = await request.get(`/api/documents/${d.document_id}?lean=true`, { headers: { "X-Member-Id": ME } });
    if (!detail.ok()) continue;
    const doc = (await detail.json()) as { page_count?: number | null; has_original?: boolean };
    if (doc.has_original && (doc.page_count ?? 0) >= 3) return { id: d.document_id, title: d.title };
  }
  return null;
}

test("a cited document opens beside the answer and can be read page by page", async ({ page, request }) => {
  test.setTimeout(90_000);
  const doc = await multiPageDocument(request);
  test.skip(!doc, "no multi-page PDF in the seeded data");
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), ME);
  await page.route("**/api/chat/sessions/*/messages", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const events = [
      { type: "text_final", text: "The clause is on page 2 [1]." },
      { type: "citation_data", ref: 1, doc_id: "doc-0", document_id: doc!.id, title: doc!.title, page: 2, quote: "",
        quotes: [{ page: 2, quote: "" }], verified: true },
    ];
    return route.fulfill({
      contentType: "text/event-stream",
      body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") + "data: [DONE]\n\n",
    });
  });
  await page.goto("/ui/chat");
  await page.getByTestId("chat-input").fill("Where is the clause?");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("source-chip").first().click();
  const panel = page.getByTestId("citation-document-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("panel-page-total")).toContainText(/of \d+/, { timeout: 30_000 });
  const total = Number((await panel.getByTestId("panel-page-total").innerText()).replace(/\D/g, ""));
  expect(total).toBeGreaterThanOrEqual(3);

  // Next / previous move the pages and the header follows.
  await panel.getByTestId("panel-page-input").fill("1");
  await panel.getByTestId("panel-page-input").press("Enter");
  await expect(panel.getByTestId("panel-page-current")).toContainText("page 1");
  await panel.getByTestId("panel-page-next").click();
  await expect(panel.getByTestId("panel-page-current")).toContainText("page 2");
  await panel.getByTestId("panel-page-prev").click();
  await expect(panel.getByTestId("panel-page-current")).toContainText("page 1");

  // The Text view jumps to a page too.
  await panel.getByTestId("panel-view-text").click();
  await expect(panel.getByTestId("panel-text-view")).toBeVisible();
  await panel.getByTestId("panel-page-input").fill("3");
  await panel.getByTestId("panel-page-input").press("Enter");
  await expect(panel.getByTestId("panel-page-current")).toContainText("page 3");

  // The workspace link keeps the page.
  await expect(panel.getByRole("link", { name: /Open in workspace/ })).toHaveAttribute("href", /page=3/);
  const id = new URL(page.url()).pathname.split("/").pop();
  if (id && id !== "chat") await request.delete(`/api/chat/sessions/${id}`, { headers: { "X-Member-Id": ME } });
});
