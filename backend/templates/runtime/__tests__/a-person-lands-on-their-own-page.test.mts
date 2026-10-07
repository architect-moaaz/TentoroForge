/**
 * Where a person lands once signed in (`lib/landing.ts`).
 *
 * ToroCommerce's administrator, signing in at `/login?callbackUrl=/`, was
 * taken to the storefront: the address won over the role's landing page, and
 * the template's sign-in page sent everyone to "/" (forge-v3, 2026-10-07).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({
  stubs: {
    "@/lib/account": "export const HOME = '/'; export const LANDING_FOR = { Admin: '/admin/products', Customer: '/' };",
  },
});

const m: any = await import("../../app-foundation/src/lib/landing.ts");

eqJson(m.afterSignIn("", "Admin"), "/admin/products", "no address: the role's own page");
eqJson(m.afterSignIn("/", "Admin"), "/admin/products", "'/' in the address is where everyone starts, not where they were");
eqJson(m.afterSignIn("http://shop.example/", "Admin"), "/admin/products", "nor is an absolute '/'");
eqJson(m.afterSignIn("/login", "Admin"), "/admin/products", "nor a way in");
eqJson(m.afterSignIn("/orders?order=7", "Customer"), "/orders?order=7", "a page they were sent away from wins");
eqJson(m.afterSignIn("http://shop.example/admin/orders", "Admin"), "http://shop.example/admin/orders",
       "kept exactly as given when it wins");
eqJson(m.afterSignIn("", "Stranger"), "/", "a role with no landing page goes home");
eqJson(m.afterSignIn(null, ""), "/", "no role yet: home");

process.env.NEXT_PUBLIC_BASE_PATH = "/preview/abc";
eqJson(m.appPath("/preview/abc/"), "/", "the preview's prefix is not part of the page");
eqJson(m.afterSignIn("/preview/abc", "Admin"), "/admin/products", "so its home is still home");

let calls = 0;
const role = await m.roleAfterSignIn(async () => (++calls < 3 ? null : { user: { role: "Admin" } }));
ok(role === "Admin" && calls === 3, "the role is read once the session has caught up");
done("landing after sign-in");
