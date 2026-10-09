// Browser check: drag a page into the Assistant, and accepting an edit card changes the document (plan 21, D1-D3).
//   python evals/history_ui_fixture.py create                          -> document_id, member
//   python evals/history_ui_fixture.py chat-edits DOC-... --member MEM-...  -> session_id
//   DOC=... MEMBER=... SESSION=... PLAYWRIGHT_PATH=frontend/node_modules/playwright \
//   CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" BASE=http://localhost:5188 \
//   SHOT_DIR=/tmp node evals/assistant_drag_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://localhost:5188";
const { DOC, MEMBER, SESSION } = process.env;
const SHOTS = process.env.SHOT_DIR || "/tmp";

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
  await page.route("**/api/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-member-id": MEMBER } }));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
  const out = {};

  // 1. Drag the page from the page list onto the Assistant tab's drop zone.
  await page.goto(`${BASE}/ui/documents/${DOC}`);
  await page.getByTestId("document-workspace").waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: /^(Pages|Parts)$/ }).click().catch(() => {});
  await page.getByRole("button", { name: "AI", exact: true }).click();
  const thumb = page.getByTestId("page-thumb").first();
  await thumb.waitFor({ timeout: 20000 });
  await thumb.dragTo(page.getByTestId("assistant-dropzone"));
  out.dropped = await page.getByTestId("assistant-pages").locator("li").allInnerTexts();
  await page.getByTestId("assistant-prompt").fill("fix the numbering on this page");
  await page.screenshot({ path: `${SHOTS}/drag_ai_tab.png` });

  // 2. Continue in Assistant: the page is attached to the message and the box is pre-filled (nothing sent).
  await page.getByTestId("assistant-send").click();
  await page.getByTestId("composer-attachments").waitFor({ timeout: 20000 });
  out.chat_attachments = await page.getByTestId("composer-attachment").allInnerTexts();
  out.chat_draft = await page.getByTestId("chat-input").inputValue();
  out.chat_url = page.url().replace(BASE, "");
  await page.screenshot({ path: `${SHOTS}/drag_chat_composer.png` });

  // 3. A page dragged straight onto the composer (from the reader on another tab) is covered by the unit of
  //    readPageDrag; here: drop the same payload on the composer to prove the drop target.
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.setData("application/x-precentis-page", JSON.stringify({ document_id: "X", filename: "Other.docx", unit: "part", number: 2 }));
    const el = document.querySelector('[data-testid="composer"]');
    el.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
    el.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  out.after_composer_drop = await page.getByTestId("composer-attachment").allInnerTexts();

  // 4. Accept the cards: the document changes, as a clean version.
  await page.goto(`${BASE}/ui/chat/${SESSION}`);
  await page.getByTestId("edit-proposals").waitFor({ timeout: 30000 });
  await page.getByTestId("edits-accept-all").click();
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="edit-status"]').length >= 2
    && Array.from(document.querySelectorAll('[data-testid="edit-status"]')).every((n) => /In the document/.test(n.textContent)), null, { timeout: 30000 });
  out.card_status = await page.getByTestId("edit-status").allInnerTexts();
  out.struck_originals_left = await page.locator('[data-testid="edit-card"] p.line-through').count();
  out.export_button = (await page.getByTestId("edits-export").innerText()).trim();
  await page.screenshot({ path: `${SHOTS}/drag_cards_applied.png` });

  // 5. The document itself now reads the new numbers, with no tracked markup, and History has the commit.
  await page.goto(`${BASE}/ui/documents/${DOC}?panel=versions`);
  await page.getByTestId("commit-log").waitFor({ timeout: 30000 });
  out.commits = await page.getByTestId("commit-message").allInnerTexts();
  await page.getByTestId("document-body").waitFor();
  out.body = (await page.getByTestId("document-body").innerText()).replace(/\s+/g, " ").slice(0, 400);
  await page.getByTestId("document-review-changes").click();
  await page.getByTestId("version-diff").waitFor({ timeout: 20000 });
  out.review = {
    replaces: await page.getByTestId("diff-replace").count(),
    first: (await page.getByTestId("diff-replace").first().innerText()).replace(/\s+/g, " "),
  };
  await page.screenshot({ path: `${SHOTS}/drag_review_changes.png` });

  out.page_errors = errors;
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
