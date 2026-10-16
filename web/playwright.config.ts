import { defineConfig, devices } from "@playwright/test";

// Screen flows against a production build, with the API replaced in each test (e2e/fake-api.ts):
// no model is called. The build points at a fake API origin that only the tests answer.
const PORT = 3100;
export const FAKE_API = "http://api.ragdog.test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: { baseURL: `http://localhost:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `npm run build && npm run start -- -p ${PORT} -H localhost`,
    url: `http://localhost:${PORT}`,
    env: { NEXT_PUBLIC_RAGDOG_API_URL: FAKE_API },
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
