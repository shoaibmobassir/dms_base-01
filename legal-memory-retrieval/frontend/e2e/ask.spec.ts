import { expect, test, type APIRequestContext } from "@playwright/test";

// Ask the Firm page. Scope wiring and rendering are checked without the language
// model (the answer payload is stubbed at the network layer); the live grounded
// answer runs only with E2E_LLM=1.

type Matter = { matter_id: string; matter_code: string; title: string; restricted: boolean };

/** A stubbed /api/answers/stream response: evidence, then the final answer. */
function sse(result: Record<string, unknown>, evidence: Record<string, unknown> = {}) {
  const events = [{ type: "evidence", ...evidence }, { type: "final", result, replaced: false }];
  return {
    contentType: "text/event-stream",
    body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") + "data: [DONE]\n\n",
  };
}

async function firstOpenMatter(request: APIRequestContext): Promise<Matter> {
  const res = await request.get("/api/matters?limit=50");
  expect(res.ok()).toBeTruthy();
  const items = ((await res.json()) as { items: Matter[] }).items.filter((m) => !m.restricted);
  expect(items.length).toBeGreaterThan(0);
  return items[0];
}

test("sidebar lists Ask the Firm and Assistant", async ({ page }) => {
  await page.goto("/ui/");
  const nav = page.getByTestId("sidebar");
  await nav.getByRole("link", { name: "Ask the Firm", exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/ask$/);
  await expect(page.getByTestId("ask-composer")).toBeVisible();
  await nav.getByRole("link", { name: "Assistant", exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/chat/);
});

test("matter page asks with a structured matter scope", async ({ page, request }) => {
  const matter = await firstOpenMatter(request);
  await page.route("**/api/answers/stream", (route) =>
    route.fulfill(sse({ answer: "Stubbed.", key_finding: "Stubbed.", abstained: false, provider: "bedrock", sources: [] })),
  );
  await page.goto(`/ui/matters/${matter.matter_id}`);
  await page.getByTestId("matter-ask").click();
  await expect(page).toHaveURL(/scopeType=matter/);
  await page.getByTestId("ask-input").fill("who is working on this matter?");
  const sent = page.waitForRequest((r) => r.url().endsWith("/api/answers/stream") && r.method() === "POST");
  await page.getByTestId("ask-submit").click();
  const body = JSON.parse((await sent).postData() ?? "{}");
  expect(body.query).toBe("who is working on this matter?");
  expect(body.scope).toEqual({ type: "matter", value: matter.matter_code });
});

test("answer renders evidence chips, people and not-found states", async ({ page }) => {
  await page.route("**/api/answers/stream", (route) =>
    route.fulfill(sse({
        status: "answered",
        abstained: false,
        provider: "bedrock",
        key_finding: "The Long Stop Date is 31 March 2027 (DOC-E9058749C1).",
        answer: "The team:\n- Helena Voss — Partner, Lead (MEM-00001, MTR-2026-00901)\n- Priya Menon — Senior Associate (MTR-2026-00901)\n\nClosing is conditional (DOC-E9058749C1).",
        sources: [
          { document_id: "DOC-E9058749C1", title: "Share Purchase Agreement.docx", matter_code: "CORP/BLR/0901/2026" },
          { document_id: "DOC-06D46C4AD1", title: "Board Resolution.docx", matter_code: "CORP/BLR/0901/2026" },
        ],
        matter_cards: [{
          matter_id: "MTR-2026-00901", matter_code: "CORP/BLR/0901/2026", title: "Acme Technologies — Series B Financing",
          client_name: "Acme Technologies Private Limited", opposing_party: "Northbridge Growth Fund II", status: "open",
          practice_area: "Corporate", court: null, opened_date: "2026-03-02", document_count: 12,
          facts: ["Series B round led by Northbridge.", "Closing is conditional on regulatory approval."],
          legal_issues: ["Long stop date mechanics"],
          team: [
            { member_id: "MEM-00001", name: "Helena Voss", role: "Partner", role_on_matter: "Lead" },
            { member_id: "MEM-00004", name: "Priya Menon", role: "Senior Associate", role_on_matter: "Member" },
          ],
          documents: [{ document_id: "DOC-E9058749C1", title: "Share Purchase Agreement.docx", document_type: "Agreement", doc_date: "2026-04-01" }],
          deadlines: [{ title: "Long stop date", kind: "contract", due_date: "2027-03-31", court: null, status: "open" }],
        }],
        resolved_scope: { kind: "matter", label: "CORP/BLR/0901/2026", method: "code", matter_ids: ["MTR-2026-00901"] },
    })),
  );
  await page.goto("/ui/ask?q=who%20is%20on%20it&scope=CORP%2FBLR%2F0901%2F2026&scopeType=matter");
  await expect(page.getByTestId("citation-DOC-E9058749C1").first()).toBeVisible();
  await expect(page.getByTestId("citation-MEM-00001")).toHaveAttribute("href", /\/people\/MEM-00001$/);
  await expect(page.getByTestId("citation-MTR-2026-00901")).toHaveAttribute("href", /\/matters\/MTR-2026-00901$/);
  await expect(page.getByTestId("citation-MEM-00001")).toHaveText("Helena Voss");
  // The matter is named once; its repeat after the next bullet is hidden.
  await expect(page.getByTestId("citation-MTR-2026-00901")).toHaveCount(1);
  // Sources: the cited document first, the retrieved-but-unused one under "Also searched".
  await expect(page.getByTestId("answer-sources")).toContainText("Share Purchase Agreement.docx");
  await expect(page.getByTestId("answer-sources")).not.toContainText("Board Resolution.docx");
  await expect(page.getByTestId("answer-sources-searched")).toContainText("Board Resolution.docx");
  await expect(page.getByTestId("citation-MTR-2026-00901")).toHaveText("CORP/BLR/0901/2026");
  // The matter brief: details, who works on it, documents and what is due.
  const brief = page.getByTestId("matter-brief");
  await expect(brief).toContainText("Acme Technologies — Series B Financing");
  await expect(brief).toContainText("Northbridge Growth Fund II");
  await expect(page.getByTestId("brief-team")).toContainText("Helena Voss");
  await expect(page.getByTestId("brief-team")).toContainText("Lead");
  await expect(page.getByTestId("brief-deadlines")).toContainText("Long stop date");
  await expect(page.getByTestId("brief-documents")).toContainText("Documents (12)");
  await expect(page.getByTestId("brief-open-matter")).toHaveAttribute("href", /\/matters\/MTR-2026-00901$/);
  await expect(page.getByTestId("answer-scope")).toContainText("CORP/BLR/0901/2026");
  await expect(page.getByTestId("ai-provider")).not.toContainText("Assembled from retrieved passages");
  // Cited documents open in the same side panel as the Assistant.
  // Document chips read as titles, and open beside the answer without covering it.
  await expect(page.getByTestId("citation-DOC-E9058749C1").first()).toHaveText("Share Purchase Agreement");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByTestId("citation-DOC-E9058749C1").first().click();
  await expect(page.getByTestId("citation-document-panel")).toContainText("Share Purchase Agreement.docx");
  const answerBox = (await page.getByTestId("ai-answer").boundingBox())!;
  const panelBox = (await page.getByTestId("document-panel-drawer").boundingBox())!;
  expect(answerBox.x + answerBox.width).toBeLessThanOrEqual(panelBox.x + 1);
  await page.getByTestId("citation-document-panel").getByLabel("Close document").click();
  await expect(page.getByTestId("citation-document-panel")).toBeHidden();
  await page.getByTestId("brief-documents").getByRole("button", { name: /Share Purchase Agreement/ }).click();
  await expect(page.getByTestId("citation-document-panel")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByTestId("answer-sources").getByRole("button").first().click();
  await expect(page.getByTestId("citation-document-panel")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("citation-document-panel")).toBeHidden();

  await page.unroute("**/api/answers/stream");
  await page.route("**/api/answers/stream", (route) =>
    route.fulfill(sse({
        status: "not_found", abstained: true, reason: "no_matching_matter", provider: "bedrock",
        answer: "No matter in the records available to you matches. The closest is MTR-2026-00901.",
    })),
  );
  await page.goto("/ui/ask?q=the%20case%20where%20acme%20challenged%20the%20bank");
  await expect(page.getByTestId("ai-not-found")).toContainText("No matter in the records");
});

test("KM panel lists matters, documents and people and hands off to the Assistant", async ({ page }) => {
  const panel = {
    matters: [
      { matter_id: "MTR-2026-00901", matter_code: "CORP/BLR/0901/2026", title: "Acme Technologies — Series B Financing",
        client_name: "Acme Technologies Private Limited", status: "open", lead: "Helena Voss", document_count: 12,
        relation: "asked", why: "asked about; 6 relevant passages" },
      { matter_id: "MTR-1931-00025", matter_code: "PIL/HAG/0025/1931", title: "German Minority Schools",
        client_name: "Germany", status: "Closed", lead: "Helena Voss", document_count: 9,
        relation: "related", why: "precedent of CORP/BLR/0901/2026" },
    ],
    documents: [
      { document_id: "DOC-E9058749C1", title: "Share Purchase Agreement.docx", document_type: "Agreement",
        matter_id: "MTR-2026-00901", matter_code: "CORP/BLR/0901/2026", page_number: 4, why: "cited in the answer", cited: true },
      { document_id: "DOC-06D46C4AD1", title: "Board Resolution.docx", document_type: "Resolution",
        matter_id: "MTR-2026-00901", matter_code: "CORP/BLR/0901/2026", why: "relevant passage", cited: false },
    ],
    people: [
      { member_id: "MEM-00001", name: "Helena Voss", role: "Partner", office: "The Hague",
        on_matters: [{ matter_id: "MTR-2026-00901", matter_code: "CORP/BLR/0901/2026", role_on_matter: "Lead" }],
        why: "Lead on CORP/BLR/0901/2026" },
      { member_id: "MEM-00004", name: "Priya Menon", role: "Senior Associate", office: "Bengaluru",
        on_matters: [], why: "author of Share Purchase Agreement.docx" },
    ],
  };
  await page.route("**/api/answers/stream", (route) =>
    route.fulfill(sse(
      { status: "answered", abstained: false, provider: "bedrock", key_finding: "Closing is conditional.",
        answer: "Closing is conditional (DOC-E9058749C1).", panel },
      { panel },
    )),
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/ui/ask?q=what%20are%20the%20closing%20conditions%20for%20acme");
  await expect(page.getByTestId("km-matter")).toHaveCount(2);
  await expect(page.getByTestId("km-matters")).toContainText("Asked about");
  await expect(page.getByTestId("km-matters")).toContainText("precedent of CORP/BLR/0901/2026");
  await expect(page.getByTestId("km-person").first()).toContainText("Lead on CORP/BLR/0901/2026");
  await expect(page.getByTestId("km-people")).toContainText("author of Share Purchase Agreement.docx");
  await expect(page.getByTestId("km-document").first()).toContainText("cited in the answer");
  // No duplicate people/sources lists beside the panel.
  await expect(page.getByTestId("answer-people")).toHaveCount(0);
  await expect(page.getByTestId("answer-sources")).toHaveCount(0);
  await page.getByTestId("km-document").first().getByRole("button").click();
  await expect(page.getByTestId("citation-document-panel")).toContainText("Share Purchase Agreement");
  await page.keyboard.press("Escape");
  const handoff = page.getByTestId("km-open-assistant");
  await expect(handoff).toHaveAttribute("href", /\/chat\?matter=MTR-2026-00901&q=what\+are\+the\+closing\+conditions/);
});

test("recent questions come from the server and can be removed", async ({ page }) => {
  let items = [
    { id: "h1", query: "Who is on the Acme deal team?", scope: null, scope_type: null, asked_at: new Date().toISOString() },
    { id: "h2", query: "What relief was sought?", scope: "CI-OPEN-001", scope_type: "matter", asked_at: new Date().toISOString() },
  ];
  await page.route("**/api/answers/history**", (route) => {
    const req = route.request();
    if (req.method() === "DELETE") {
      const id = req.url().split("/").pop();
      items = items.filter((i) => i.id !== id);
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ json: { items } });
  });
  await page.goto("/ui/ask");
  const list = page.getByTestId("ask-history");
  await expect(list.getByTestId("ask-history-item")).toHaveCount(2);
  await expect(list).toContainText("CI-OPEN-001");
  await list.getByRole("button", { name: /Remove “Who is on the Acme deal team\?”/ }).click();
  await expect(list.getByTestId("ask-history-item")).toHaveCount(1);
  await page.route("**/api/answers/stream", (route) => route.fulfill(sse({ status: "answered", abstained: false, answer: "ok" })));
  await page.route("**/api/answers/saved/h2", (route) =>
    route.fulfill({
      json: {
        query: "What relief was sought?",
        answer: "ok",
        key_finding: "ok",
        abstained: false,
        saved: true,
        saved_id: "h2",
        scope: "CI-OPEN-001",
        sources: [],
        panel: { matters: [], documents: [], people: [] },
      },
    }),
  );
  await list.getByText("What relief was sought?").click();
  await expect(page).toHaveURL(/\/ui\/ask\/h2/);
  await expect(page.getByTestId("ask-from-cache")).toBeVisible();
});

test("verified answers cite exact spans and report removed statements", async ({ page }) => {
  await page.route("**/api/answers/stream", (route) =>
    route.fulfill(sse({
        status: "answered",
        abstained: false,
        provider: "bedrock",
        key_finding: "The Board approved the transfer on 12 September 2026 [1].",
        answer: "The Board approved the transfer on 12 September 2026 [1]. The matter is open (MTR-2026-00901).",
        span_citations: [{
          ref: 1, document_id: "DOC-06D46C4AD1", title: "Board Resolution.docx", support: "supported",
          quotes: [
            { quote: "Passed at the meeting of the Board of Directors held on 12 September 2026", page: 1 },
            { quote: "consent of the Board be and is hereby accorded to the transfer", page: 1 },
          ],
        }],
        grounding: { checked: 3, supported: 2, partial: 0, removed: 1 },
    })),
  );
  await page.goto("/ui/ask?q=when%20was%20the%20transfer%20approved");
  await expect(page.getByTestId("span-citation-1").first()).toBeVisible();
  await expect(page.getByTestId("ai-grounding-removed")).toContainText("1 statement was removed");
  await page.getByTestId("span-citation-1").first().click();
  const panel = page.getByTestId("citation-document-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("panel-quote")).toContainText("held on 12 September 2026");
  await expect(page.getByTestId("panel-quote-switcher")).toContainText("1/2");
  await page.getByTestId("panel-quote-switcher").getByLabel("Next quote").click();
  await expect(page.getByTestId("panel-quote")).toContainText("accorded to the transfer");
});

test("saved answer opens by id and does not POST the stream", async ({ page }) => {
  const answerId = `ask-${Date.now()}`;
  let streamPosts = 0;
  await page.route(`**/api/answers/saved/${answerId}`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "Have we prepared a brief note?",
        answer: "Stored answer body.",
        key_finding: "Stored key finding.",
        abstained: false,
        provider: "bedrock",
        status: "answered",
        saved: true,
        saved_id: answerId,
        sources: [],
        matter_cards: [],
        panel: { matters: [], documents: [], people: [] },
      }),
    });
  });
  await page.route("**/api/answers/stream", (route) => {
    streamPosts += 1;
    return route.fulfill(sse({ answer: "Should not stream.", key_finding: "no", abstained: false, provider: "bedrock", sources: [] }));
  });
  await page.goto(`/ui/ask/${answerId}`);
  await expect(page.getByTestId("ai-answer")).toBeVisible();
  await expect(page.getByTestId("ask-from-cache")).toBeVisible();
  await expect(page.getByTestId("ask-question")).toContainText("Have we prepared a brief note?");
  await expect(page.getByText("Stored key finding.")).toBeVisible();
  expect(streamPosts).toBe(0);
});

test.describe("Ask the Firm with the language model", () => {
  test.skip(!process.env.E2E_LLM, "set E2E_LLM=1 to exercise the language model");

  test("a scoped question gets a grounded answer, not the extractive fallback", async ({ page, request }) => {
    test.setTimeout(150_000);
    const matter = await firstOpenMatter(request);
    await page.goto(`/ui/ask?q=${encodeURIComponent("explain this")}&scope=${encodeURIComponent(matter.matter_code)}&scopeType=matter`);
    await expect(page.getByTestId("ai-answer")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("ai-provider")).not.toContainText("Assembled from retrieved passages");
    await expect(page.getByTestId("answer-sources")).toBeVisible();
  });
});
