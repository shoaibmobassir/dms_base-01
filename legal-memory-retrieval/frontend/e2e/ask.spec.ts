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
        answer: "The team:\n- Helena Voss — Partner, Lead (MEM-00001, MTR-2026-00901)\n\nClosing is conditional (DOC-E9058749C1).",
        sources: [{ document_id: "DOC-E9058749C1", title: "Share Purchase Agreement.docx", matter_code: "CORP/BLR/0901/2026" }],
        matter_cards: [{ matter_id: "MTR-2026-00901", team: [{ member_id: "MEM-00001", name: "Helena Voss", role: "Partner", role_on_matter: "Lead" }] }],
        resolved_scope: { kind: "matter", label: "CORP/BLR/0901/2026", method: "code", matter_ids: ["MTR-2026-00901"] },
    })),
  );
  await page.goto("/ui/ask?q=who%20is%20on%20it&scope=CORP%2FBLR%2F0901%2F2026&scopeType=matter");
  await expect(page.getByTestId("citation-DOC-E9058749C1").first()).toBeVisible();
  await expect(page.getByTestId("citation-MEM-00001")).toHaveAttribute("href", /\/people\/MEM-00001$/);
  await expect(page.getByTestId("citation-MTR-2026-00901")).toHaveAttribute("href", /\/matters\/MTR-2026-00901$/);
  await expect(page.getByTestId("answer-people")).toContainText("Helena Voss");
  await expect(page.getByTestId("answer-scope")).toContainText("CORP/BLR/0901/2026");
  await expect(page.getByTestId("ai-provider")).not.toContainText("Assembled from retrieved passages");

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
