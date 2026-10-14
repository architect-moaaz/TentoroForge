import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: { signIn: "/login" },
});

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
