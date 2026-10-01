// Copy pdf.js runtime assets (image decoders, standard fonts, character maps,
// colour profiles) into public/ so the viewer can load them at /ui/pdfjs/.
// They are generated from node_modules and not committed.
import { cpSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const from = path.join(root, "node_modules", "pdfjs-dist");
const to = path.join(root, "public", "pdfjs");

rmSync(to, { recursive: true, force: true });
mkdirSync(to, { recursive: true });
for (const dir of ["wasm", "standard_fonts", "cmaps", "iccs"]) {
  cpSync(path.join(from, dir), path.join(to, dir), { recursive: true });
}
console.log(`pdf.js assets copied to ${path.relative(root, to)}`);
