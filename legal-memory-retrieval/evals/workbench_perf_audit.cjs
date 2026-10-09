// Memory and frame budget of the workbench with 20 open tabs (plan 22, W7.1).
//   PW=/path/to/frontend/node_modules/playwright BASE=http://127.0.0.1:8021 node evals/workbench_perf_audit.cjs
// Creates an "E2E-TMP perf" project with 19 short text documents and one generated 400-page Word file (removed by
// scripts/e2e_cleanup.py), opens all 20 in tabs, cycles through them and scrolls. Gates: JS heap after 20 tabs,
// p95 tab-switch time, p95 frame time while scrolling. Writes evals/last_workbench_perf.json; exit 1 on a miss.
const fs = require("fs");
const { execFileSync } = require("child_process");
const { chromium } = require(process.env.PW);
const BASE = process.env.BASE || "http://127.0.0.1:8021";
const M = process.env.MEMBER || "MEM-00001";
const h = { "X-Member-Id": M };
const GATE = { heap_mb: 700, switch_p95_ms: 600, frame_p95_ms: 50 };
const p95 = (xs) => [...xs].sort((a, b) => a - b)[Math.max(0, Math.ceil(xs.length * 0.95) - 1)] ?? 0;

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const api = ctx.request;
  const pid = (await (await api.post(BASE + "/api/projects", { headers: h, data: { title: "E2E-TMP perf" } })).json()).project_id;
  const upload = async (name, mimeType, buffer) => {
    const b = await (await api.post(BASE + "/api/uploads/batches", { headers: h, multipart: { container_kind: "project", container_id: pid, files: { name, mimeType, buffer } } })).json();
    return (await (await api.post(BASE + `/api/uploads/batches/${b.batch_id}/run`, { headers: h })).json()).batch.files[0].document_id;
  };
  const big = "/tmp/perf-400.docx";
  execFileSync(".venv/bin/python", ["-c", `from evals.long_doc.generate import build_document, to_docx; to_docx(build_document(400, 5), "${big}")`]);
  await upload("perf-400-pages.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", fs.readFileSync(big));
  for (let i = 1; i <= 19; i++) await upload(`perf-note-${String(i).padStart(2, "0")}.txt`, "text/plain", Buffer.from(`E2E-TMP note ${i}. ` + "The notice period is ninety days. ".repeat(200)));

  const page = await ctx.newPage();
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), M);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => (await cdp.send("Performance.getMetrics")).metrics.find((m) => m.name === "JSHeapUsedSize").value / 1048576;
  await page.goto(`${BASE}/ui/work/project/${pid}`);
  await page.getByTestId("explorer-document").first().waitFor();
  const baseline = await heap();

  const rows = page.getByTestId("explorer-document");
  const n = Math.min(20, await rows.count());
  const open = [];
  for (let i = 0; i < n; i++) {
    const t0 = Date.now();
    await rows.nth(i).locator("button").first().dblclick();
    await page.getByTestId("workbench-tab").nth(i).waitFor();
    await page.waitForTimeout(250);
    open.push(Date.now() - t0);
  }
  await page.waitForTimeout(2000);
  const heapAfterOpen = await heap();

  const tabs = page.getByTestId("workbench-tab");
  const switches = [];
  for (let round = 0; round < 3; round++)
    for (let i = 0; i < n; i++) {
      const t0 = Date.now();
      await tabs.nth(i).locator("button").first().click();
      await page.locator("[data-testid=document-viewer], [data-testid=viewer-scroll], [data-testid=document-workspace]").first().waitFor({ timeout: 10000 }).catch(() => {});
      switches.push(Date.now() - t0);
    }
  await tabs.nth(0).locator("button").first().click();
  await page.waitForTimeout(1500);
  const frames = await page.evaluate(async () => {
    const el = document.querySelector("[data-testid=viewer-scroll]");
    if (!el) return { missing: true };
    const out = []; let last = performance.now();
    for (let i = 0; i < 120; i++) {
      el.scrollTop += 60;
      await new Promise((r) => requestAnimationFrame(r));
      const now = performance.now(); out.push(now - last); last = now;
    }
    return { out, height: el.scrollHeight };
  });
  await page.waitForTimeout(1000);
  const frameList = frames.out || [];
  const heapEnd = await heap();

  const r = {
    tabs_open: n, heap_mb: { baseline: +baseline.toFixed(1), after_open: +heapAfterOpen.toFixed(1), after_cycling: +heapEnd.toFixed(1) },
    open_each_ms_p95: p95(open), switch_ms: { p50: [...switches].sort((a, b) => a - b)[Math.floor(switches.length / 2)], p95: p95(switches) },
    frame_ms: { p50: [...frameList].sort((a, b) => a - b)[60], p95: +p95(frameList).toFixed(1), max: +Math.max(...frameList).toFixed(1), scrolled_px_height: frames.height }, gate: GATE,
  };
  r.pass = n >= 20 && frameList.length === 120 && frames.height > 20000 && heapEnd < GATE.heap_mb && r.switch_ms.p95 < GATE.switch_p95_ms && r.frame_ms.p95 < GATE.frame_p95_ms;
  console.log(JSON.stringify(r, null, 2));
  fs.writeFileSync("evals/last_workbench_perf.json", JSON.stringify(r, null, 2));
  await browser.close();
  process.exit(r.pass ? 0 : 1);
})().catch((e) => { console.error("FAIL", e.message); process.exit(2); });
