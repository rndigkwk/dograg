import type { NextConfig } from "next";

// Where the browser may load from (docs/security/2026-10-16-pre-login-review.md). Scripts and styles
// keep 'unsafe-inline': Next.js inlines its bootstrap and Leaflet sets inline styles; a nonce would
// make every page dynamic. Everything else is listed: the API, Supabase Auth, the map tiles, the home photos.
const API = new URL(process.env.NEXT_PUBLIC_RAGDOG_API_URL || "https://ragdog-api-892238791473.asia-northeast3.run.app").origin;
const SUPABASE = new URL(process.env.NEXT_PUBLIC_SUPABASE_URL || "https://ffdahevkdymdaxcexkth.supabase.co").origin; // sign-in (P4)
const DEV = process.env.NODE_ENV !== "production";

const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${DEV ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://images.unsplash.com https://tile.openstreetmap.org",
  "font-src 'self' data:",
  `connect-src 'self' ${API} ${SUPABASE}${DEV ? " ws:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" }, // older browsers; frame-ancestors above for the rest
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(self), camera=(), microphone=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  // The Playwright build (playwright.config.ts) goes to its own folder, so running the screen
  // tests does not overwrite the files of a dev server that is running at the same time.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
