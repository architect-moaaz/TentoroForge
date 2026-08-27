"use client";

/**
 * App Router global error boundary — catches React render crashes
 * that escape every downstream boundary. Reports the error to Forge
 * (self-healing loop picks it up), then shows a minimal recovery UI.
 *
 * Placed at src/app/global-error.tsx by runtime_injector — Next.js
 * requires this exact path for the root-level boundary.
 */

import { useEffect } from "react";
import { reportFromError } from "@/lib/error_reporter";

export default function GlobalError({
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
      source_file: "src/app/global-error.tsx",
      user_context: error.digest ? { digest: error.digest } : undefined,
    });
  }, [error]);

  return (
    <html>
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            padding: "2rem",
            background: "#f8fafc",
            color: "#0f172a",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 600 }}>
            Something went wrong
          </h1>
          <p style={{ marginTop: "0.75rem", color: "#475569", maxWidth: 480, textAlign: "center" }}>
            The page crashed while rendering. The error has been reported and a fix
            will be attempted automatically.
          </p>
          {error.message ? (
            <pre
              style={{
                marginTop: "1rem",
                padding: "0.75rem 1rem",
                background: "#e2e8f0",
                color: "#334155",
                borderRadius: 6,
                maxWidth: 640,
                overflow: "auto",
                fontSize: "0.85rem",
              }}
            >
              {error.message}
            </pre>
          ) : null}
          <button
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.5rem 1.25rem",
              background: "#0f172a",
              color: "white",
              border: 0,
              borderRadius: 6,
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
