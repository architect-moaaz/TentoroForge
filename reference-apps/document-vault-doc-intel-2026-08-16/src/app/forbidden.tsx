import Link from "next/link";
import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * 403 — permission denied. Spec C5.
 * Routed to explicitly by middleware / auth guards when the user is
 * signed in but lacks the role for a page.
 * `Document Intelligence` and `/documents` are substituted per app.
 */
export default function Forbidden() {
  return (
    <EdgePageFrame code="403" title="You don't have access to that page">
      <p>
        Your account doesn't have permission for this area of Document Intelligence. If
        that's a mistake, ask an administrator to grant you access.
      </p>
      <Link href="/documents" className="edge-cta">
        Return to Document Intelligence
      </Link>
    </EdgePageFrame>
  );
}
