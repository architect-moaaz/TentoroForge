import Link from "next/link";
import { auth } from "@/auth";
import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * 403 — permission denied. Spec C5.
 * Routed to explicitly by middleware / auth guards when the user is
 * signed in but lacks the role for a page.
 *
 * "Return to" goes where THIS person lands, not where the app's first
 * page is. The link once pointed every role at one route, and on an app
 * whose first page was the doctor's, an administrator or a parent pressing
 * it arrived straight back here — the reviewer recorded the link as doing
 * nothing. `LANDING_FOR` is the per-role map nav-flow carries (the same
 * one the root redirect reads); a role it does not name, or a request with
 * no session, falls back to the app's signed-in front door.
 * `{{app_name}}`, `{{landing_for}}` and `{{home_route}}` are substituted per app.
 */
const LANDING_FOR: Record<string, string> = {{landing_for}};
const LANDING = "{{home_route}}";

export default async function Forbidden() {
  const session = await auth();
  const role = (session?.user as { role?: string } | undefined)?.role;
  const home = (role && LANDING_FOR[role]) || LANDING;
  return (
    <EdgePageFrame code="403" title="You don't have access to that page">
      <p>
        Your account doesn't have permission for this area of {{app_name}}. If
        that's a mistake, ask an administrator to grant you access.
      </p>
      <Link href={home} className="edge-cta">
        Return to {{app_name}}
      </Link>
    </EdgePageFrame>
  );
}
