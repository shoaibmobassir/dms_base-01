import { FolioDocxReviewer } from "@stll/folio-core/server";
import fs from "node:fs";
import path from "node:path";

const IN = process.argv[2], OUT = process.argv[3];
const results = [];
const tableCells = JSON.parse(fs.readFileSync(path.join(IN, "..", "table_cells.json"), "utf8"));
const words = (t) => t.split(/\s+/).filter((w) => /^[A-Za-z]{4,}$/.test(w));
for (const f of fs.readdirSync(IN).filter((x) => x.endsWith(".docx")).sort()) {
  const buf = fs.readFileSync(path.join(IN, f));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  const row = { file: f };
  try {
    let t = performance.now();
    const r = await FolioDocxReviewer.fromBuffer(ab, { author: "Bench Editor" });
    const snap = r.snapshot();
    row.open_ms = Math.round(performance.now() - t);
    row.blocks = snap.blocks.length;
    const kinds = {};
    for (const b of snap.blocks) kinds[b.kind] = (kinds[b.kind] || 0) + 1;
    row.kinds = kinds;
    // round trip, no edits
    t = performance.now();
    const rt = await r.save();
    row.roundtrip_save_ms = Math.round(performance.now() - t);
    row.roundtrip_type = rt.type;
    if (rt.buffer) fs.writeFileSync(path.join(OUT, f.replace(".docx", ".roundtrip.docx")), Buffer.from(rt.buffer));
    // tracked edits: one ordinary paragraph and one table cell
    const r2 = await FolioDocxReviewer.fromBuffer(ab, { author: "Bench Editor" });
    const s2 = r2.snapshot();
    const cellTexts = new Set((tableCells[f] || []).map((t) => t.replace(/\s+/g, " ").trim()));
    const inTable = (b) => cellTexts.has(b.text.replace(/\s+/g, " ").trim());
    const para = s2.blocks.find((b) => !inTable(b) && words(b.text).length >= 6);
    const cell = s2.blocks.find((b) => inTable(b) && words(b.text).length >= 1);
    const ops = [];
    const edits = [];
    for (const [label, b] of [["paragraph", para], ["table_cell", cell]]) {
      if (!b) continue;
      const w = words(b.text)[0];
      ops.push({ id: label, type: "replaceInBlock", blockId: b.id, find: w, replace: `${w}EDITED` });
      edits.push({ label, find: w, block_text: b.text.slice(0, 120) });
    }
    row.edits = edits;
    t = performance.now();
    const res = r2.applyOperations(ops, { mode: "tracked-changes" });
    const saved = await r2.save();
    row.edit_save_ms = Math.round(performance.now() - t);
    row.applied = (res.applied || []).map((a) => a.id ?? a.operationId ?? a);
    row.skipped = (res.skipped || []).map((s) => `${s.id ?? s.operationId}:${s.reason}`);
    if (saved.buffer) fs.writeFileSync(path.join(OUT, f.replace(".docx", ".edited.docx")), Buffer.from(saved.buffer));
    row.changes = r2.getChanges ? r2.getChanges().length : null;
  } catch (e) {
    row.error = String(e && e.message || e).slice(0, 300);
  }
  results.push(row);
  console.log(JSON.stringify(row));
}
fs.writeFileSync(path.join(OUT, "folio.json"), JSON.stringify(results, null, 2));
