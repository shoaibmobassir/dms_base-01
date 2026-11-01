// Temporary: dev server for browser checks against the worktree API on :8021. Not committed.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(rootDir, "./src") } },
  server: { port: 5188, strictPort: true, proxy: { "/api": "http://127.0.0.1:8021" } },
});
