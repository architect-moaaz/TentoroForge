/**
 * THE TEST VERSION SAYS SO. When the app runs as its test side
 * (FORGE_ENVIRONMENT=test, set by Publish to Test) every page carries a small
 * label and asks search engines not to index it; on the live app this renders
 * nothing. Forge runtime — refreshed on every publish.
 */
export function TestRibbon() {
  if (process.env.FORGE_ENVIRONMENT !== "test") return null;
  return (
    <>
      <meta name="robots" content="noindex, nofollow" />
      <div
        role="status"
        data-forge-test-ribbon=""
        style={{
          position: "fixed",
          left: 8,
          bottom: 8,
          zIndex: 2147483000,
          background: "#92400e",
          color: "#ffffff",
          font: "600 12px/1.5 system-ui, -apple-system, sans-serif",
          padding: "3px 10px",
          borderRadius: 999,
          boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
          pointerEvents: "none",
        }}
      >
        Test version — not the live app
      </div>
    </>
  );
}
