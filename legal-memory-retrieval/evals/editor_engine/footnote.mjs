import { FolioDocxReviewer, FOLIO_DOCUMENT_OPERATION_CONTRACT_VERSION } from "@stll/folio-core/server";
import fs from "node:fs";
const buf = fs.readFileSync(process.argv[2]);
const r = await FolioDocxReviewer.fromBuffer(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), { author: "Bench Editor" });
const stories = r.listStories();
console.log("stories", JSON.stringify(stories.map((s) => s.handle ?? s)).slice(0, 400));
const results = {};
for (const [label, handle, find] of [["footnote", { type: "footnote", noteId: 1 }, "Handbook"], ["header", null, "Confidential"]]) {
  let h = handle;
  if (!h) { const hs = stories.map((s) => s.handle ?? s).find((s) => s.type === "header"); h = hs; }
  const snap = r.snapshotStory(h);
  const block = snap && snap.blocks.find((b) => b.text.includes(find));
  if (!block) { results[label] = "no block"; continue; }
  const res = r.applyDocumentOperationsToStory({ story: h, snapshot: snap, batch: { version: FOLIO_DOCUMENT_OPERATION_CONTRACT_VERSION, mode: "tracked-changes",
    operations: [{ id: label, type: "replaceInBlock", blockId: block.id, find, replace: find + "EDITED" }] } });
  results[label] = { status: res.status, receipts: JSON.stringify(res.receipts ?? res.operations ?? res).slice(0, 160) };
}
const saved = await r.save();
fs.writeFileSync(process.argv[3], Buffer.from(saved.buffer));
console.log(JSON.stringify(results), saved.type);
