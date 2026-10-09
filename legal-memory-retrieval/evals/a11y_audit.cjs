// Accessibility audit of the workbench (plan 22, W7.2): runs axe-core over each workbench view in a real browser.
//
// axe-core is MPL-2.0, so it is not a project dependency: fetch it yourself (`npm i axe-core` anywhere) and pass the
// file:   AXE_PATH=/path/to/node_modules/axe-core/axe.min.js PW=/path/to/frontend/node_modules/playwright \
//         BASE=http://127.0.0.1:8021 node evals/a11y_audit.cjs
// Needs the API + built UI on BASE and the demo database. Creates an "E2E-TMP a11y" project (removed by
// scripts/e2e_cleanup.py). Writes evals/last_a11y_audit.json and exits 1 on any serious/critical violation.
const fs = require("fs");
const { chromium } = require(process.env.PW);
const AXE = fs.readFileSync(process.env.AXE_PATH, "utf8");
const BASE = process.env.BASE || "http://127.0.0.1:8021";
const M = process.env.MEMBER || "MEM-00001";
const h = { "X-Member-Id": M };

async function audit(page, name, report) {
  await page.waitForTimeout(500);
  await page.evaluate(AXE);
  const r = await page.evaluate(async () => {
    const out = await window.axe.run(document, { resultTypes: ["violations"], runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] });
    return out.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, count: v.nodes.length,
      nodes: v.nodes.slice(0, 4).map((n) => ({ target: n.target.join(" "), html: n.html.slice(0, 140) })) }));
  });
  report[name] = r;
  const bad = r.filter((v) => v.impact === "serious" || v.impact === "critical");
  console.log(`${name.padEnd(28)} ${String(r.length).padStart(2)} violations, ${bad.length} serious/critical`);
  for (const v of bad) console.log(`    [${v.impact}] ${v.id}: ${v.help} (${v.count})  e.g. ${v.nodes[0].target}`);
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const api = ctx.request;
  const p = await (await api.post(BASE + "/api/projects", { headers: h, data: { title: "E2E-TMP a11y" } })).json();
  const pid = p.project_id;
  const mk = async (name, body) => {
    const b = await (await api.post(BASE + "/api/uploads/batches", { headers: h, multipart: { container_kind: "project", container_id: pid, files: { name, mimeType: "text/plain", buffer: Buffer.from(body) } } })).json();
    return (await (await api.post(BASE + `/api/uploads/batches/${b.batch_id}/run`, { headers: h })).json()).batch.files[0].document_id;
  };
  const d1 = await mk("a11y-one.txt", "E2E-TMP the notice period is ninety days.");
  const d2 = await mk("a11y-two.txt", "E2E-TMP liability is capped at the fees paid.");
  await api.post(BASE + "/api/tabular/reviews", { headers: h, data: { title: "A11y review", kind: "project", id: pid, document_ids: [d1, d2], columns: [{ preset: "parties" }, { preset: "term" }] } });
  const page = await ctx.newPage();
  await page.addInitScript((id) => localStorage.setItem("precentis.persona", id), M);
  const report = {};

  await page.goto(`${BASE}/ui/projects`);
  await page.getByTestId("new-project").waitFor();
  await audit(page, "projects list", report);
  await page.getByTestId("new-project").click();
  await page.getByTestId("new-project-dialog").waitFor();
  await audit(page, "new project dialog", report);
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/ui/work/project/${pid}`);
  await page.getByTestId("explorer-document").first().waitFor();
  await audit(page, "workbench explorer", report);
  await page.getByTestId("explorer-section-library").click();
  await audit(page, "explorer + library section", report);
  await page.getByTestId("explorer-document").first().locator("button").first().dblclick();
  await page.getByTestId("workbench-tab").first().waitFor();
  await page.waitForTimeout(2500);
  await audit(page, "document in a tab", report);
  await page.getByTestId("explorer-document").nth(1).locator("button").first().click({ modifiers: ["Alt"] });
  await page.getByTestId("editor-group-1").waitFor();
  await page.waitForTimeout(2500);
  await audit(page, "two editor groups", report);
  for (const [id, name, ready] of [["activity-search", "search view", "workbench-search"], ["activity-assistant", "assistant view", "workbench-assistant"],
    ["activity-reviews", "reviews view", "workbench-reviews"], ["activity-playbooks", "playbooks view", "workbench-playbooks"], ["activity-changes", "changes view", "workbench-changes"]]) {
    await page.getByTestId(id).click();
    await page.getByTestId(ready).waitFor();
    await audit(page, name, report);
  }
  await page.getByTestId("activity-reviews").click();
  await page.getByTestId("reviews-item").first().click();
  await page.getByTestId("review-table").waitFor();
  await page.waitForTimeout(3000);
  await audit(page, "tabular review table", report);
  await page.getByTestId("review-cell").first().click();
  await page.getByTestId("review-cell-dialog").waitFor();
  await audit(page, "review cell dialog", report);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+p");
  await page.getByTestId("quick-open").waitFor();
  await audit(page, "quick open", report);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+Shift+p");
  await page.getByTestId("workbench-commands").waitFor();
  await audit(page, "command list", report);

  fs.writeFileSync("evals/last_a11y_audit.json", JSON.stringify(report, null, 2));
  const serious = Object.values(report).flat().filter((v) => v.impact === "serious" || v.impact === "critical").length;
  await browser.close();
  process.exit(serious ? 1 : 0);
})().catch((e) => { console.error("FAIL", e.message); process.exit(2); });
