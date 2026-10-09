// Browser check for the Ask page's Refresh control (docs/experiments/ask_saved_answers_test_2026-10-02.md).
// Expected after the fix: one POST per click, the URL id unchanged, and no further requests.
//   PLAYWRIGHT_PATH=frontend/node_modules/playwright CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
//   BASE=http://127.0.0.1:8021 node evals/ask_refresh_loop_check.cjs
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:8021";
const H = { "x-member-id": "MEM-00001" };
const UUID = /\/ui\/ask\/([0-9a-f-]{36})/;
const q = `Appeal No. 163 of 2018, have we prepared a brief note of arguments? debug ${Math.random().toString(16).slice(2, 8)}`;

(async () => {
  // Seed a saved answer through the API, so the browser starts from /ask/:id.
  const seed = await fetch(`${BASE}/api/answers`, { method: "POST", headers: { ...H, "content-type": "application/json" }, body: JSON.stringify({ query: q, k: 10 }) });
  const id1 = (await seed.json()).saved_id;
  console.log("seeded", id1);

  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
  const page = await (await browser.newContext()).newPage();
  await page.route("**/api/**", (route) => route.continue({ headers: { ...route.request().headers(), ...H } }));
  const t0 = Date.now();
  const stamp = () => `${((Date.now() - t0) / 1000).toFixed(1)}s`;
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) console.log(stamp(), "console", m.type(), m.text().slice(0, 200)); });
  page.on("pageerror", (e) => console.log(stamp(), "pageerror", e.message.slice(0, 200)));
  page.on("request", (r) => { if (r.url().includes("/api/answers") && !r.url().includes("/history")) console.log(stamp(), "REQ", r.method(), new URL(r.url()).pathname.replace(/[0-9a-f-]{36}/, ":id")); });
  page.on("response", (r) => { if (r.url().includes("/api/answers") && !r.url().includes("/history")) console.log(stamp(), "RES", r.status(), new URL(r.url()).pathname.replace(/[0-9a-f-]{36}/, ":id")); });
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) console.log(stamp(), "NAV", f.url().replace(BASE, "")); });

  await page.goto(`${BASE}/ui/ask/${id1}`);
  await page.waitForSelector('[data-testid="ask-refresh"]', { timeout: 30000 });
  console.log(stamp(), "refresh visible; clicking");
  await page.getByTestId("ask-refresh").click();
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(5000);
    const txt = (await page.innerText("main").catch(() => "")).replace(/\s+/g, " ");
    console.log(stamp(), page.url().replace(BASE, ""), "| refresh-btn:", await page.getByTestId("ask-refresh").count(), "| gathering:", /Searching the firm/.test(txt), "| h1:", (await page.getByTestId("ask-question").innerText().catch(() => "")).slice(0, 30));
  }
  await page.screenshot({ path: (process.env.SHOT_PATH || "/tmp/ask_refresh_shot.png") });
  await browser.close();
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
