import { withAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

// A call to the API is answered, not sent somewhere: a person without a
// session is redirected to the sign-in page, a client that is not a browser
// cannot follow that and read HTML where it expected JSON. `/api/*` answers
// 401 as JSON, the shape the data route uses.
const isApi = (path: string) => path === "/api" || path.startsWith("/api/");

export default withAuth(
  function middleware(req) {
    if (!req.nextauth.token && isApi(req.nextUrl.pathname)) {
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
    // runs; an API call is let through to it, which answers it.
    callbacks: { authorized: ({ token, req }) => !!token || isApi(req.nextUrl.pathname) },
  },
);

// Excludes:
//   login/signup/set-password/api/auth — auth flow itself (set-password is
//     where an invite or reset link lands; the visitor holding one has no
//     password yet, so a gate would send them to a sign-in they cannot do)
//   editor + api/editor + api/figma — (dev-only) routes; the editor has no
//     login concept and runs only in dev. Excluded so devs can hit /editor
//     without authenticating. The (dev-only) route group is tree-shaken
//     in production builds via next.config.ts.
//   api/cron + api/webhooks — called by machines (the scheduler's tick, another
//     system's signed call); each authenticates itself and can hold no session
//   _next, favicon, files with extensions — static assets
export const config = {
  matcher: [
    "/((?!login|signup|set-password|api/auth|api/cron|api/webhooks|api/editor|api/figma|editor|_next|favicon.ico|.*\\..*).*)",
  ],
};
