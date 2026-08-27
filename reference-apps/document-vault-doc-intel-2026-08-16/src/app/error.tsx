"use client";
import { useEffect } from "react";
import Link from "next/link";
import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * 500 — server error boundary for the app router. Spec C5.
 * `Document Intelligence` and `/documents` are substituted per app.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("[app-error]", error);
  }, [error]);

  return (
    <EdgePageFrame code="500" title="Something went wrong on our end">
      <p>
        We hit an unexpected problem loading this page. Try again in a moment
        — if it keeps happening, refresh the page or head back to{" "}
        <Link href="/documents" className="edge-inline-link">
          Document Intelligence
        </Link>
        .
      </p>
      {error?.digest && (
        <p className="edge-meta">
          Reference: <code>{error.digest}</code>
        </p>
      )}
      <button type="button" onClick={() => reset()} className="edge-cta">
        Try again
      </button>
    </EdgePageFrame>
  );
}
