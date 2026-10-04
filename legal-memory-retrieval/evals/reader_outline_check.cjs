// Browser check of the document reader on a Word file without page rendition (Parts): only headings look like
// headings, the outline shows clean labels and jumps to the right part, and the toolbar names the section being read.
//   DOC=... MEMBER=... PLAYWRIGHT_PATH=frontend/node_modules/playwright CHROME_PATH=... BASE=http://localhost:5188 \
//   SHOT_DIR=/tmp node evals/reader_outline_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://localhost:5188";
const { DOC, MEMBER } = process.env;
const SHOTS = process.env.SHOT_DIR || "/tmp";

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
  await page.route("**/api/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-member-id": MEMBER } }));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
  const out = {};
  await page.goto(`${BASE}/ui/documents/${DOC}`);
  await page.getByTestId("document-body").waitFor({ timeout: 30000 });
  await page.waitForTimeout(800);
  out.part1 = await page.getByTestId("document-body").locator(":scope > div").evaluateAll((els) =>
    els.map((e) => ({ text: e.innerText.replace(/\s+/g, " ").slice(0, 60), heading: e.className.includes("font-display") })));
  out.toolbar_section_part1 = await page.getByTestId("document-toolbar").innerText().then((t) => t.split("\n").find((l) => /—|\d\./.test(l)) || null);
  out.outline = await page.getByTestId("document-outline").locator("button").evaluateAll((els) => els.map((e) => e.innerText.replace(/\n/g, " | ")));
  await page.screenshot({ path: `${SHOTS}/reader_part1.png` });
  await page.getByTestId("document-outline").getByRole("button", { name: /Change of Control/ }).click();
  await page.waitForTimeout(1000);
  out.after_jump_url = page.url().replace(BASE, "");
  out.after_jump_body = (await page.getByTestId("document-body").innerText()).replace(/\s+/g, " ").slice(0, 160);
  out.toolbar_after_jump = await page.getByTestId("document-toolbar").innerText().then((t) => t.split("\n").filter((l) => /Change of Control|Part|\/ /.test(l)));
  await page.screenshot({ path: `${SHOTS}/reader_jump.png` });
  out.page_errors = errors;
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
