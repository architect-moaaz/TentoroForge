import Link from "next/link";
import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * 403 — permission denied. Spec C5.
 * Routed to explicitly by middleware / auth guards when the user is
 * signed in but lacks the role for a page.
 * `{{app_name}}` and `{{home_route}}` are substituted per app.
 */
export default function Forbidden() {
  return (
    <EdgePageFrame code="403" title="You don't have access to that page">
      <p>
        Your account doesn't have permission for this area of {{app_name}}. If
        that's a mistake, ask an administrator to grant you access.
      </p>
      <Link href="{{home_route}}" className="edge-cta">
        Return to {{app_name}}
      </Link>
    </EdgePageFrame>
  );
}
