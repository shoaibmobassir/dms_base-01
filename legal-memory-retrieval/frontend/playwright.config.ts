import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(here, "..");
const PORT = Number(process.env.E2E_PORT ?? 8010);
// Second stack with firm sign-in on: API with AUTH_ENABLED + OIDC against scripts/fake_idp.py.
const AUTH_PORT = 8011;
const IDP_PORT = 8012;
const python = `"${path.join(backendDir, ".venv/bin/python")}"`;

/**
 * End-to-end tests drive the built SPA (`npm run build` → ../static) served by the
 * real API against the seeded Postgres. Expected values are read from the API at
 * test time — nothing in the UI or the tests is hard-coded demo data.
 *
 *   python scripts/migrate.py && python scripts/seed_demo.py   # once
 *   npm run build && npm run test:e2e
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    channel: process.env.E2E_BROWSER_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "app", testIgnore: /auth\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${PORT}` } },
    { name: "auth", testMatch: /auth\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${AUTH_PORT}` } },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.api.main:app --port ${PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${PORT}/api/system/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { AUTH_ENABLED: "false" },
    },
    {
      command: `${python} scripts/fake_idp.py --port ${IDP_PORT}`,
      cwd: backendDir,
      // The member the fake IdP signs in as (must exist in the seeded database).
      env: { FAKE_IDP_EMAIL: process.env.E2E_SIGNIN_EMAIL ?? "helena.voss@harbourchambers.int" },
      url: `http://127.0.0.1:${IDP_PORT}/.well-known/openid-configuration`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `${python} -m uvicorn app.api.main:app --port ${AUTH_PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${AUTH_PORT}/api/system/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        AUTH_ENABLED: "true",
        OIDC_ISSUER: `http://127.0.0.1:${IDP_PORT}`,
        OIDC_CLIENT_ID: "precentis-e2e",
        OIDC_CLIENT_SECRET: "e2e-secret",
        OIDC_REDIRECT_URI: `http://127.0.0.1:${AUTH_PORT}/api/auth/callback`,
        SESSION_COOKIE_SECURE: "false",
        ALLOW_API_KEY_BROWSER_LOGIN: "false",
      },
    },
  ],
});
