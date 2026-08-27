import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: { signIn: "/login" },
});

// Excludes:
//   login/signup/api/auth — auth flow itself
//   editor + api/editor + api/figma — (dev-only) routes; the editor has no
//     login concept and runs only in dev. Excluded so devs can hit /editor
//     without authenticating. The (dev-only) route group is tree-shaken
//     in production builds via next.config.ts.
//   _next, favicon, files with extensions — static assets
export const config = {
  matcher: [
    "/((?!login|signup|api/auth|api/editor|api/figma|editor|_next|favicon.ico|.*\\..*).*)",
  ],
};
