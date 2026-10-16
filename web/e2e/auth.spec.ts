import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const SUPABASE = "https://ffdahevkdymdaxcexkth.supabase.co";

test("sign-in starts Google with PKCE and comes back to this site's callback", async ({ page }) => {
  await fakeApi(page, [], { "/places/kinds": [], "/places/regions": {} });
  let authorize: URL | null = null;
  await page.route(`${SUPABASE}/auth/v1/authorize**`, (route) => {
    authorize = new URL(route.request().url());
    return route.fulfill({ status: 200, body: "stopped before Google" });
  });
  await page.goto("/places");
  await page.getByRole("button", { name: "Google로 로그인" }).click();
  await expect.poll(() => authorize).not.toBeNull();
  const url = authorize as unknown as URL;
  expect(url.searchParams.get("provider")).toBe("google");
  expect(url.searchParams.get("code_challenge_method")).toBe("s256");
  expect(url.searchParams.get("code_challenge")?.length).toBeGreaterThan(40);
  expect(url.searchParams.get("redirect_to")).toMatch(/^http:\/\/localhost:3100\/auth\/callback$/);
  // The verifier stays in this browser (on this site's origin): the code alone cannot be traded for a session.
  await page.goBack();
  await expect(page).toHaveURL(/\/places$/);
  const verifier = await page.evaluate(() => Object.keys(localStorage).some((key) => key.endsWith("-code-verifier")));
  expect(verifier).toBe(true);
});

test("a failed or unfinished sign-in says so", async ({ page }) => {
  await page.goto("/auth/callback?error=access_denied&error_description=denied");
  await expect(page.getByRole("alert").filter({ hasText: "로그인하지 못했습니다" })).toBeVisible();
  await expect(page.getByRole("link", { name: "홈으로" })).toHaveAttribute("href", "/");
});
