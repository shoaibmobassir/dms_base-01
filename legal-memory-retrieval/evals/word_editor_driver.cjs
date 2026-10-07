// Drives the real Word editor (Folio) for evals/word_editor_roundtrip_eval.py.
//   PW=... node evals/word_editor_driver.cjs BASE MEMBER DOC_ID "paragraph text" "table cell text"
// Opens /documents/:id/write, types one marker after the paragraph text and one in the table cell, saves, prints JSON.
const { chromium } = require(process.env.PW);
const [BASE, MEMBER, DOC, PARA, CELL] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), MEMBER);
  const t0 = Date.now();
  const T0 = Date.now();
  await page.goto(`${BASE}/ui/documents/${DOC}/write`);
  await page.getByTestId("full-word-editor").waitFor({ timeout: 120000 });
  await page.getByText("Tracking: On").waitFor({ timeout: 120000 });
  const openMs = Date.now() - t0;
  const out = { open_ms: openMs, para_clicked: false, cell_clicked: false };
  // Folio pages scroll inside nested containers: centre the element ourselves, then click its middle
  const focusOn = async (loc) => {
    // pages far from the top are painted only when scrolled near (the editor's hidden model also holds the text,
    // so look for the painted layout runs): wheel down until the text appears
    await page.mouse.move(900, 500);
    for (let i = 0; i < 400 && (await loc.count()) === 0; i++) {
      await page.mouse.wheel(0, 1200);
      await page.waitForTimeout(40);
    }
    await loc.waitFor({ timeout: 60000 });
    if (process.env.DEBUG_LOC) console.error("loc", await loc.count(), await loc.evaluate((el) => el.outerHTML.slice(0, 160) + " | " + el.parentElement.outerHTML.slice(0, 200)), JSON.stringify(await loc.boundingBox()));
    await loc.evaluate((el) => el.scrollIntoView({ block: "center", inline: "center" }));
    await page.waitForTimeout(300);
    const box = await loc.boundingBox();
    await page.mouse.click(box.x + Math.min(box.width / 2, 40), box.y + box.height / 2);
  };
  await focusOn(page.locator(".layout-line").filter({ hasText: PARA }).first());
  await page.keyboard.press("End");
  await page.keyboard.type(" [WE-PARA-EDIT]");
  out.para_clicked = true;
  await focusOn(page.locator(".layout-run").filter({ hasText: new RegExp(`^${CELL}$`) }).first());
  await page.keyboard.press("End");
  await page.keyboard.type(" [WE-CELL-EDIT]");
  out.cell_clicked = true;
  await page.waitForTimeout(Number(process.env.SETTLE_MS || 500));
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
  await page.getByTestId("full-editor-save").click();
  await page.getByTestId("full-editor-note").fill("word editor round-trip eval");
  let serverMs = null, sentBytes = 0;
  const reqlog = [];
  page.on("requestfinished", (req) => { if (process.env.REQLOG) { const t = req.timing(); reqlog.push(`${req.method()} ${req.url().replace(BASE, "").slice(0, 70)} start=${Math.round(t.startTime - T0)} dur=${Math.round(t.responseEnd - t.requestStart)}ms`); } });
  page.on("requestfinished", async (req) => {
    if (req.url().includes("/save-docx")) { const t = req.timing(); serverMs = Math.round(t.responseEnd - t.requestStart); sentBytes = (req.postDataBuffer() || Buffer.alloc(0)).length; }
  });
  if (process.env.CAPTURE) await page.route("**/save-docx", (route) => { require("fs").writeFileSync(process.env.CAPTURE, route.request().postDataBuffer()); route.continue(); });
  const s0 = Date.now();
  await page.getByTestId("full-editor-confirm").click();
  await page.getByTestId("full-editor-save-dialog").waitFor({ state: "hidden", timeout: 120000 });
  out.save_ms = Date.now() - s0;
  out.save_request_ms = serverMs;
  out.save_bytes = sentBytes;
  if (process.env.REQLOG) out.requests = reqlog.slice(-30);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.log(JSON.stringify({ error: e.message })); process.exit(2); });
