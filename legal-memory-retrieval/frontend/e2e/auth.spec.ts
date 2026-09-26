import { expect, test } from "@playwright/test";

// Runs against the "auth" project: API with AUTH_ENABLED=true and OIDC pointing at
// scripts/fake_idp.py, which signs real ID tokens for helena.voss@… (MEM-00001).

test("unauthenticated users see firm sign-in, not the app or a key box", async ({ page }) => {
  await page.goto("/ui/matters");
  await expect(page.getByTestId("sign-in")).toBeVisible();
  await expect(page.getByTestId("sign-in-oidc")).toBeVisible();
  await expect(page.getByLabel("API key")).toHaveCount(0);
  expect((await page.request.get("/api/matters")).status()).toBe(401);
});

test("firm sign-in → session cookie → app → sign-out", async ({ page, context }) => {
  await page.goto("/ui/matters");
  await page.getByTestId("sign-in-oidc").click();
  await expect(page).toHaveURL(/\/ui\/matters$/); // returned to the page asked for
  await expect(page.getByTestId("matters-table")).toBeVisible();

  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "precentis_session");
  expect(session?.httpOnly).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain("precentis_session"); // not readable by scripts

  // A write goes through (CSRF token echoed from the readable cookie).
  const matterId = (await (await page.request.get("/api/matters?status=Open&limit=1")).json()).items[0].matter_id;
  await page.goto(`/ui/matters/${matterId}`);
  await page.getByTestId("matter-pin").click();
  await expect(page.getByTestId("sidebar-pinned")).toBeVisible();
  await page.getByTestId("matter-pin").click();

  // Sign out revokes the server session.
  await page.getByTestId("user-menu").click();
  await page.getByTestId("sign-out").click();
  await expect(page.getByTestId("sign-in")).toBeVisible();
  const stale = await context.request.get("/api/matters", { headers: { Cookie: `precentis_session=${session!.value}` } });
  expect(stale.status()).toBe(401);
});

test("a write without the CSRF token is refused", async ({ page }) => {
  await page.goto("/ui/");
  await page.getByTestId("sign-in-oidc").click();
  await expect(page.getByTestId("topbar")).toBeVisible();
  const matterId = (await (await page.request.get("/api/matters?status=Open&limit=1")).json()).items[0].matter_id;
  expect((await page.request.put(`/api/matters/${matterId}/pin`)).status()).toBe(403);
});
