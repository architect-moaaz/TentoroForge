// Where a person goes once they have signed in — one rule for every sign-in
// form the app has (the SDK's `useSignIn` and the template's `useLogin`).
//
// THE ADMINISTRATOR LANDED ON THE SHOP. ToroCommerce's admin, signing in at
// `/login?callbackUrl=/`, was taken to the storefront rather than the admin
// console: the address's `callbackUrl` won over the role's landing page, and
// the template's sign-in page sent everyone to "/" whatever their role
// (forge-v3, 2026-10-07). A `callbackUrl` is where someone was sent away
// from; "/" and the sign-in pages are not that — they are where everybody
// starts. Those go to the role's own landing page.
import * as accountModule from "@/lib/account";
import { HOME } from "@/lib/account";

/** Where each role lands, by the role's name (`lib/account.ts`). An app
 *  projected before the map existed has none, and everyone goes HOME. */
const LANDING_FOR: Record<string, string> =
  ((accountModule as unknown as { LANDING_FOR?: Record<string, string> }).LANDING_FOR) ?? {};

/** Pages that are a way in, not a destination. */
const WAYS_IN = new Set(["/login", "/signup", "/sign-in", "/sign-up", "/set-password", "/register"]);

/** The app path a `callbackUrl` names: same-origin absolute URLs and the
 *  preview's path prefix taken off. */
export function appPath(url: string): string {
  let path = url;
  try {
    const u = new URL(url, "http://app.local");
    path = u.pathname;
  } catch { /* a bare path */ }
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
  if (base && path.startsWith(base)) path = path.slice(base.length) || "/";
  return path.replace(/\/+$/, "") || "/";
}

/** The page a signed-in role starts on. */
export function landingFor(role: string | null | undefined): string {
  return (role && LANDING_FOR[role]) || HOME;
}

/** Where to go after signing in: the page they were sent away from, or their
 *  role's own landing page when what the address names is only a way in. */
export function afterSignIn(callbackUrl: string | null | undefined, role: string | null | undefined): string {
  const to = (callbackUrl ?? "").trim();
  if (to) {
    const path = appPath(to);
    if (path !== "/" && path !== HOME && !WAYS_IN.has(path)) return to;
  }
  return landingFor(role);
}

/** The signed-in role, read once the session has caught up: the session
 *  cookie can land a moment after `signIn` resolves, and a role read too
 *  early sent the person HOME. */
export async function roleAfterSignIn(
  getSession: () => Promise<{ user?: unknown } | null>,
): Promise<string> {
  for (let i = 0; i < 5; i++) {
    const role = String(((await getSession())?.user as { role?: unknown } | undefined)?.role ?? "");
    if (role) return role;
    await new Promise((r) => setTimeout(r, 150));
  }
  return "";
}
