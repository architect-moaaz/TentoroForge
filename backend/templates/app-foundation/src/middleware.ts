import { withAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

// The scaffold's gate, until the application's own is written from its
// Blueprint (`project_middleware`). Same shape: every route reaches this, and
// which are open is decided here on exact routes — never on how a path starts,
// which let `/login-history` and `/payroll` through a list of words.

// A call to the API is answered, not sent somewhere: a person without a
// session is redirected to the sign-in page, a client that is not a browser
// cannot follow that and read HTML where it expected JSON. `/api/*` answers
// 401 as JSON, the shape the data route uses.
const isApi = (path: string) => path === "/api" || path.startsWith("/api/");

// Open to a signed-out visitor, each matched whole (`services/blueprint/platform_routes.py`).
const PUBLIC_ROUTES: RegExp[] = [
  new RegExp("^/login$"),                   // where a person signs in
  new RegExp("^/signup$"),                  // where a person makes an account
  new RegExp("^/set-password$"),            // where an invite or reset link lands
  new RegExp("^/offline$"),                 // what an installed app shows with no network
  new RegExp("^/pay(?:/.*)?$"),             // the stand-in checkout, for a guest's cart too
  new RegExp("^/api/auth(?:/.*)?$"),        // the sign-in machinery itself
  new RegExp("^/api/cron(?:/.*)?$"),        // the scheduler's tick, which carries CRON_SECRET
  new RegExp("^/api/webhooks(?:/.*)?$"),    // another system's signed call
  new RegExp("^/api/pay(?:/.*)?$"),         // the stand-in checkout's answers
  new RegExp("^/api/mcp(?:/.*)?$"),         // an assistant's calls, which carry their own token
  // (dev-only) the editor has no login concept and runs only in dev; the
  // (dev-only) route group is tree-shaken from production builds.
  new RegExp("^/editor(?:/.*)?$"),
  new RegExp("^/api/editor(?:/.*)?$"),
  new RegExp("^/api/figma(?:/.*)?$"),
];
const isPublic = (path: string) => PUBLIC_ROUTES.some((r) => r.test(path));

export default withAuth(
  function middleware(req) {
    const path = req.nextUrl.pathname;
    if (isPublic(path)) return NextResponse.next();
    if (!req.nextauth.token && isApi(path)) {
      return NextResponse.json(
        { error: { code: "UNAUTHORIZED", message: "Sign in to use this." } },
        { status: 401 },
      );
    }
    return NextResponse.next();
  },
  {
    pages: { signIn: "/login" },
    // `withAuth` redirects every unauthorised request before the function above
    // runs; an API call and a public route are let through to it.
    callbacks: {
      authorized: ({ token, req }) => !!token || isApi(req.nextUrl.pathname) || isPublic(req.nextUrl.pathname),
    },
  },
);

// Only the framework's files and static files (by extension) skip the gate.
export const config = {
  matcher: [
    "/((?!_next/|.*\\.(?:ico|png|jpg|jpeg|gif|svg|webp|avif|css|js|map|txt|xml|json|webmanifest|woff|woff2|ttf|otf|pdf|mp4|webm|mp3|wasm)$).*)",
  ],
};
