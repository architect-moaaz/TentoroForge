/**
 * Who is asking, for the billing routes: the signed-in person, and where the
 * app is (its origin and base path), for the addresses a gateway sends people
 * back to. Forge runtime — do not remove.
 */
import { auth } from "@/auth";

export interface Person { id: string; email?: string | null; name?: string | null }

export async function person(): Promise<Person | null> {
  const session = await auth();
  const su = session?.user as { id?: string; email?: string | null; name?: string | null } | undefined;
  return su?.id ? { id: String(su.id), email: su.email ?? null, name: su.name ?? null } : null;
}

/** The app's own origin, as the person reached it — behind a proxy too (the
 *  same reading the workflow route makes for a checkout's return pages);
 *  the configured address only when the request says nothing. */
export function originOf(req: Request): string {
  const url = new URL(req.url);
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || "";
  const proto = req.headers.get("x-forwarded-proto") || url.protocol.replace(":", "");
  if (host) return `${proto.split(",")[0].trim()}://${host.split(",")[0].trim()}`;
  const configured = String(process.env.NEXT_PUBLIC_APP_URL ?? process.env.NEXTAUTH_URL ?? "").replace(/\/$/, "");
  return configured || url.origin;
}

export const basePath = () => (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

/** Asked by this app's own pages. A page of another site — or a sibling
 *  sub-domain, which the browser's same-site rule lets through — cannot
 *  subscribe someone, or cancel their plan, with their cookie. */
export function fromThisApp(req: Request): boolean {
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return false;
  const origin = req.headers.get("origin");
  return !origin || origin === originOf(req);
}

/** A path inside this app to send someone on to — never another site. */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  const n = String(next ?? "");
  return n.startsWith("/") && !n.startsWith("//") && !n.includes("\\") ? n : fallback;
}

export function accessCookie(res: { cookies: { set: (o: any) => void } }, token: { value: string; maxAge: number } | null) {
  // NO ACCESS, NO COOKIE. Left in place, the last one kept the app open for
  // the hours it was signed for after the person cancelled or their plan ended.
  res.cookies.set({ name: "forge_access", value: token?.value ?? "", httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
    path: basePath() || "/", maxAge: token ? token.maxAge : 0 });
}
