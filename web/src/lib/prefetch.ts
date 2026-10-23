// Data the pages can draw before any script runs (2026-10-24). The data, places and fee pages fetched
// their tables in the browser after the page loaded, so the largest paint waited for the API
// (Lighthouse LCP 2.9-3.1 s, 2.2 s of it on the data page). These tables change at most daily: the
// page's server component fetches them, Vercel keeps the page for a day (`export const revalidate =
// 86400` in each page, a literal as Next requires), and the browser fetches only when the server could not.

/** `load()`'s value, or null when it fails or takes longer than `ms` (a build without network): the page
 * then loads in the browser as before. 30 s by default: the API scales to zero and takes 15-27 s to
 * wake, and a page built without its data would stay so for the day. Only the build and the daily
 * refresh wait for it, never a visitor. */
export async function prefetched<T>(load: () => Promise<T>, ms = 30_000): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  try {
    return await Promise.race([load(), late]);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
