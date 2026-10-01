import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Remove the E2E-TMP records the specs created (matters, clients, conflict checks).
export default function globalTeardown() {
  const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
  execFileSync(path.join(backend, ".venv/bin/python"), ["scripts/e2e_cleanup.py"], { cwd: backend, stdio: "inherit" });
}
