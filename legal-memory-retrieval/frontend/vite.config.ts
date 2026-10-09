import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "./src"),
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: false,
  },
  server: {
    // Bind IPv4 so http://127.0.0.1:5173 works (default is often [::1] only).
    host: "127.0.0.1",
    port: Number(process.env.VITE_PORT ?? 5173),
    proxy: {
      // VITE_API_PROXY points a second checkout's dev server at its own API (e.g. a worktree on :8021).
      "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000",
    },
  },
});
