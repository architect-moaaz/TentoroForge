/**
 * This application's session cookie — named once, read by both sides.
 *
 * A browser sends cookies by HOST, not by port, so two generated apps on
 * localhost overwrite each other's session and each then reads a token it
 * cannot decrypt ("JWT_SESSION_ERROR: decryption operation failed"). The name
 * is therefore derived from this app's own NEXTAUTH_SECRET.
 *
 * BOTH SIDES HAVE TO AGREE, AND ONE OF THEM IS THE MIDDLEWARE. `auth.ts` sets
 * the cookie; `middleware.ts` reads it through `withAuth`, which asks
 * `getToken` for next-auth's DEFAULT name unless it is told otherwise. Named
 * in auth.ts alone, every page redirected to /login while a valid session sat
 * in the browser — sign in, bounce back, sign in again (the Vercel deploy of
 * 0l133sp2, 2026-09-21).
 *
 * No `node:crypto` here: middleware runs on the edge runtime, so the digest is
 * a plain FNV-1a over the secret. It only has to differ between apps, not
 * resist anything — the secret itself never leaves the server.
 */

function fingerprint(secret: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < secret.length; i++) {
    hash ^= secret.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/** https, by the same reading next-auth's own `getToken` uses. */
function isSecure(): boolean {
  return (process.env.NEXTAUTH_URL ?? "").startsWith("https://") || Boolean(process.env.VERCEL);
}

/** `forge-<app>` — this application's prefix for every auth cookie. */
export function sessionCookiePrefix(): string {
  return `forge-${fingerprint(process.env.NEXTAUTH_SECRET || "dev-secret")}`;
}

/** The name `auth.ts` writes and `middleware.ts` must look for. */
export function sessionCookieName(): string {
  return `${isSecure() ? "__Secure-" : ""}${sessionCookiePrefix()}.session-token`;
}

/** The full `cookies` block for NextAuthOptions. */
export function sessionCookies() {
  const secure = isSecure();
  const base = sessionCookiePrefix();
  const options = { httpOnly: true, sameSite: "lax" as const, path: "/", secure };
  return {
    sessionToken: { name: sessionCookieName(), options },
    callbackUrl: { name: `${secure ? "__Secure-" : ""}${base}.callback-url`,
                   options: { ...options, httpOnly: false } },
    csrfToken: { name: `${secure ? "__Host-" : ""}${base}.csrf-token`, options },
  };
}
