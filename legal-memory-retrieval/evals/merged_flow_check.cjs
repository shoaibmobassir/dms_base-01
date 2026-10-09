// End to end in Chrome with the live model, on the document page of new_frontend_v2 + docs-search-versioning:
// drag a page onto the Assistant ask box, ask, accept the edit cards, and see the document change (no tracked text).
//   python evals/history_ui_fixture.py copy DOC-7405413EC8 --member MEM-00001   -> a throwaway copy
//   DOC=... MEMBER=... PLAYWRIGHT_PATH=frontend/node_modules/playwright CHROME_PATH=... BASE=http://localhost:5188 \
//   SHOT_DIR=/tmp node evals/merged_flow_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://localhost:5188";
const { DOC, MEMBER } = process.env;
const SHOTS = process.env.SHOT_DIR || "/tmp";
const ASK = process.env.ASK || "renumber the sections on this page so they run in order";

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
  await page.route("**/api/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-member-id": MEMBER } }));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
  const out = {};

  // 1. The document page: drag page 1 from the page list onto the Assistant ask box.
  await page.goto(`${BASE}/ui/documents/${DOC}`);
  await page.getByTestId("document-workspace").waitFor({ timeout: 30000 });
  await page.waitForTimeout(1500);
  out.view_mode = await page.getByTestId("document-toolbar").innerText().then((t) => (/Pages/.test(t) ? "pages available" : "text"));
  await page.getByRole("button", { name: /^(Pages|Parts)$/ }).first().click().catch(() => {});
  await page.getByRole("button", { name: "Assistant", exact: true }).click();
  const thumb = page.getByTestId("page-thumb").first();
  await thumb.waitFor({ timeout: 20000 });
  await thumb.dragTo(page.getByTestId("document-ai-ask"));
  out.chips = await page.getByTestId("assistant-pages").locator("li").allInnerTexts();
  await page.getByTestId("document-ai-input").fill(ASK);
  await page.screenshot({ path: `${SHOTS}/merged_ask.png` });

  // 2. Send: the conversation opens with the page attached and answers at once.
  await page.getByTestId("document-ai-send").click();
  await page.getByTestId("message-attachments").first().waitFor({ timeout: 30000 });
  out.sent_with = await page.getByTestId("message-attachments").first().innerText();
  await page.getByTestId("edit-proposals").waitFor({ timeout: 240000 });
  // The answer finishes (it is checked against its sources) before its cards can be decided.
  await page.waitForFunction(() => !document.querySelector('button[aria-label="Stop"]'), null, { timeout: 300000 });
  await page.waitForTimeout(500);
  out.cards = await page.getByTestId("edit-card").evaluateAll((els) => els.map((e) => e.innerText.replace(/\s+/g, " ").slice(0, 90)));
  await page.screenshot({ path: `${SHOTS}/merged_cards.png` });

  // 3. Accept all: the edits go into the document.
  const all = page.getByTestId("edits-accept-all");
  if (await all.count()) await all.click();
  else await page.getByTestId("edit-accept").first().click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('[data-testid="edit-status"]')).some((n) => /In the document/.test(n.textContent)), null, { timeout: 60000 });
  out.status = await page.getByTestId("edit-status").allInnerTexts();
  out.struck_left = await page.locator('[data-testid="edit-card"] p.line-through').count();

  // 4. The document: History has the commit, Review changes shows old → new, the outline reads the new numbers.
  await page.goto(`${BASE}/ui/documents/${DOC}?panel=versions`);
  await page.getByTestId("commit-log").waitFor({ timeout: 30000 });
  out.commits = await page.getByTestId("commit-message").allInnerTexts();
  await page.getByTestId("document-review-changes").click();
  await page.getByTestId("version-diff").waitFor({ timeout: 30000 });
  out.review = await page.getByTestId("diff-replace").allInnerTexts().then((x) => x.map((t) => t.replace(/\s+/g, " ")));
  await page.screenshot({ path: `${SHOTS}/merged_review.png` });
  await page.keyboard.press("Escape");
  const outline = page.getByTestId("document-outline");
  if (await outline.count()) out.outline = await outline.locator("button").allInnerTexts().then((x) => x.map((t) => t.split("\n")[0]));
  out.page_errors = errors;
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
