import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * Scheduled maintenance page. Spec C5.
 *
 * Not part of Next's built-in file conventions — a custom route ops
 * can enable via env flag / middleware when the app is doing a
 * planned outage. `Document Intelligence` is substituted per app.
 */
export default function Maintenance() {
  return (
    <EdgePageFrame code="503" title="Document Intelligence is briefly offline for maintenance">
      <p>
        We're rolling out an update. Come back in a few minutes — everything
        will pick up where you left off.
      </p>
      <p className="edge-meta">If this stays up longer than expected, contact your administrator.</p>
    </EdgePageFrame>
  );
}
