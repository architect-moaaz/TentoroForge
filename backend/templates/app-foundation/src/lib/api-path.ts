/**
 * The app's own API, under its base path.
 *
 * A fetch to "/api/…" is not prefixed by Next.js the way a Link or a router
 * push is: behind the platform's preview prefix every workflow run, every
 * list and every upload went to the platform's own origin and answered 404
 * ("Add Item to Cart failed — Something went wrong (404)", ECom L4,
 * 2026-10-11). The prefix is `NEXT_PUBLIC_BASE_PATH`, empty for a published
 * app, so a call written through here works in both.
 */
export const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export function apiPath(path: string): string {
  return `${BASE_PATH}${path.startsWith("/") ? path : `/${path}`}`;
}
