import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * App-level loading state. Spec C5.
 *
 * Rendered while the App Router's route transition is pending. Uses the
 * app's brand monogram + a shimmer, so a slow route reads as "the app
 * is preparing", not "the browser is broken".
 */
export default function Loading() {
  return (
    <EdgePageFrame variant="loading" title="Loading…">
      <div className="edge-shimmer-row" aria-hidden="true">
        <span className="edge-shimmer" style={{ width: "60%" }} />
        <span className="edge-shimmer" style={{ width: "45%" }} />
        <span className="edge-shimmer" style={{ width: "72%" }} />
      </div>
    </EdgePageFrame>
  );
}
