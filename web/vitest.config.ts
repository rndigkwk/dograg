import { defineConfig } from "vitest/config";

// Unit tests only; the screen flows in e2e/ run with Playwright (npm run e2e).
export default defineConfig({ test: { include: ["src/**/*.test.ts"] } });
