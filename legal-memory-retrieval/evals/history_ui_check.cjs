// Browser check of the document History view (docs/plan/21_documents_search_versioning.md, C3).
//   python evals/history_ui_fixture.py create            -> {"document_id": "DOC-...", "member": "MEM-..."}
//   DOC=DOC-... MEMBER=MEM-... PLAYWRIGHT_PATH=frontend/node_modules/playwright \
//   CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" BASE=http://localhost:5188 \
//   SHOT_DIR=/tmp node evals/history_ui_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://localhost:5188";
const DOC = process.env.DOC;
const MEMBER = process.env.MEMBER;
const SHOTS = process.env.SHOT_DIR || "/tmp";

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
  await page.route("**/api/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-member-id": MEMBER } }));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
  const out = {};

  await page.goto(`${BASE}/ui/documents/${DOC}?panel=versions`);
  await page.getByTestId("commit-log").waitFor({ timeout: 30000 });
  const commits = await page.getByTestId("commit").evaluateAll((els) =>
    els.map((e) => ({ v: e.dataset.version, text: e.innerText.replace(/\s+/g, " ").trim().slice(0, 140) })));
  out.log = { count: commits.length, newest_first: commits.map((c) => c.v), top: commits[0]?.text, messages: await page.getByTestId("commit-message").allInnerTexts() };
  await page.screenshot({ path: `${SHOTS}/history_rail.png` });

  // Changes of the newest commit (the INR change is version 2, the date change version 3)
  await page.locator('[data-testid="commit"][data-version="2"] [data-testid="commit-changes"]').click();
  await page.getByTestId("version-diff").waitFor({ timeout: 20000 });
  const replace = page.getByTestId("diff-replace").first();
  out.inr_change = {
    old: (await replace.locator("del").innerText()).trim(),
    new: (await replace.locator("ins").innerText()).trim(),
    has_arrow_between: (await replace.innerText()).includes("→"),
    stats: await page.getByTestId("diff-stats").innerText(),
    unchanged_blocks: await page.getByTestId("diff-unchanged").count(),
  };
  await page.screenshot({ path: `${SHOTS}/history_changes_inr.png` });

  // Who wrote what
  await page.getByTestId("changes-tab-blame").click();
  await page.getByTestId("blame").waitFor({ timeout: 20000 });
  out.blame = await page.getByTestId("blame-row").evaluateAll((rows) => rows.map((r) => ({ v: r.dataset.version, text: r.innerText.replace(/\s+/g, " ").slice(0, 70) })));
  await page.screenshot({ path: `${SHOTS}/history_blame.png` });
  await page.keyboard.press("Escape");

  // Restore version 1
  await page.locator('[data-testid="commit"][data-version="1"] [data-testid="commit-restore"]').click();
  await page.getByTestId("restore-note").fill("Client preferred the original terms");
  await page.screenshot({ path: `${SHOTS}/history_restore_dialog.png` });
  await page.getByTestId("restore-confirm").click();
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="commit"]').length >= 4, null, { timeout: 30000 });
  await page.waitForTimeout(800);
  const after = await page.getByTestId("commit").evaluateAll((els) => els.map((e) => ({
    v: e.dataset.version, current: !!e.querySelector('[data-testid="commit-current"]'), text: e.innerText.replace(/\s+/g, " ").slice(0, 120) })));
  out.after_restore = after;
  await page.screenshot({ path: `${SHOTS}/history_after_restore.png` });

  out.page_errors = errors;
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
