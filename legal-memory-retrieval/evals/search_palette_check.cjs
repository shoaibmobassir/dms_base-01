// Browser check of the ⌘K search palette (docs/plan/21_documents_search_versioning.md, B1).
//   PLAYWRIGHT_PATH=frontend/node_modules/playwright CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
//   BASE=http://127.0.0.1:5188 node evals/search_palette_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:5188";
const H = { "x-member-id": process.env.MEMBER || "MEM-00001" };

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext()).newPage();
  let failSearch = false;
  await page.route("**/api/**", (route) => {
    if (failSearch && route.request().url().includes("/api/search")) return route.fulfill({ status: 500, body: "boom" });
    return route.continue({ headers: { ...route.request().headers(), ...H } });
  });
  const out = {};
  await page.goto(`${BASE}/ui/`);
  await page.waitForTimeout(1500);

  const search = async (text, wait = 1800) => {
    // The top-bar Search button opens the same palette as the keyboard shortcut.
    await page.getByRole("button", { name: /search/i }).first().click();
    const input = page.getByTestId("command-input");
    await input.waitFor({ timeout: 10000 });
    await input.fill(text);
    await page.waitForTimeout(wait);
    return page.locator("[cmdk-list]").innerText();
  };

  let text = await search("impleadment rejoinder");
  out.content_query = { shows_document: /Impleadment|impleadment/.test(text), shows_snippet: (await page.getByTestId("search-snippet").count()) > 0, says_no_results: (await page.getByTestId("search-empty").count()) > 0 };
  await page.screenshot({ path: process.env.SHOT_DIR ? `${process.env.SHOT_DIR}/palette_content.png` : "/tmp/palette_content.png" });
  await page.keyboard.press("Escape");

  text = await search("x");
  out.one_char = { hint: /at least 2 characters/.test(text) };
  await page.keyboard.press("Escape");

  failSearch = true;
  text = await search("knowledge and belief", 12000); // the data layer retries a failed request before giving up
  out.server_error = { shows_failed: (await page.getByTestId("search-error").count()) > 0, wrongly_says_no_results: (await page.getByTestId("search-empty").count()) > 0 };
  failSearch = false;
  await page.keyboard.press("Escape");

  text = await search("zzzzqqqq");
  out.nothing_found = { says_no_matches: (await page.getByTestId("search-empty").count()) > 0 };

  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
