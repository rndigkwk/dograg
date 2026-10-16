import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Playwright build (playwright.config.ts) goes to its own folder, so running the screen
  // tests does not overwrite the files of a dev server that is running at the same time.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
