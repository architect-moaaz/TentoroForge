"use client";

/**
 * Dashboard route-segment error boundary.
 *
 * WHY THIS EXISTS: a throw in the SERVER portion of a route (before JSX is
 * returned) — e.g. a missing/corrupt `src/schemas/<route>.json`, an `auth()`
 * failure, or a bad data binding — is NOT caught by the client-side
 * `SchemaPageBoundary` (that only wraps the Engine's render). Without a
 * segment-level `error.tsx`, such a throw bubbles all the way to
 * `app/global-error.tsx`, which renders its own <html><body> and replaces the
 * ENTIRE app with a full-screen "Something went wrong" — the intermittent
 * "server component 500 / blank app" testers hit.
 *
 * This boundary lives INSIDE the (dashboard) layout, so when a single page's
 * server code throws, the app chrome (sidebar/nav) stays intact and only the
 * content area shows a recoverable error with a Retry. The error is reported to
 * Forge so the self-healing loop can pick it up.
 */

import { useEffect } from "react";
import { reportFromError } from "@/lib/error_reporter";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportFromError(error, {
      kind: "page_render",
      page_route: typeof window !== "undefined" ? window.location.pathname : undefined,
      source_file: "src/app/(dashboard)/error.tsx",
      user_context: error.digest ? { digest: error.digest } : undefined,
    });
  }, [error]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <div
        style={{
          maxWidth: 520,
          width: "100%",
          borderRadius: 12,
          border: "1px solid rgba(127,127,127,0.18)",
          background: "hsl(var(--card, 0 0% 100%))",
          color: "hsl(var(--foreground, 222 47% 11%))",
          padding: "1.75rem",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 650 }}>
          This page couldn&apos;t load
        </h1>
        <p style={{ marginTop: "0.6rem", opacity: 0.75, fontSize: "0.925rem", lineHeight: 1.5 }}>
          Something went wrong while loading this page. The rest of the app is fine —
          you can retry, or head back to the dashboard.
        </p>
        {error?.message ? (
          <pre
            style={{
              marginTop: "1rem",
              padding: "0.7rem 0.85rem",
              background: "rgba(127,127,127,0.10)",
              borderRadius: 8,
              fontSize: "0.75rem",
              textAlign: "left",
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {error.message}
          </pre>
        ) : null}
        <div style={{ marginTop: "1.25rem", display: "flex", gap: "0.6rem", justifyContent: "center" }}>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              padding: "0.5rem 1.1rem",
              borderRadius: 8,
              border: "none",
              cursor: "pointer",
              fontWeight: 600,
              fontSize: "0.875rem",
              background: "hsl(var(--primary, 221 83% 53%))",
              color: "hsl(var(--primary-foreground, 0 0% 100%))",
            }}
          >
            Retry
          </button>
          <a
            href="/"
            style={{
              padding: "0.5rem 1.1rem",
              borderRadius: 8,
              border: "1px solid rgba(127,127,127,0.25)",
              cursor: "pointer",
              fontWeight: 600,
              fontSize: "0.875rem",
              textDecoration: "none",
              color: "inherit",
            }}
          >
            Dashboard
          </a>
        </div>
      </div>
    </div>
  );
}
