import * as React from "react";
import "./EdgePageFrame.css";

/**
 * Shared frame for 404 / 500 / 403 / loading / maintenance. Spec C5.
 *
 * Chrome-less full-viewport centered card. Colours pulled from CSS
 * custom properties (--primary, --background, --card, --foreground,
 * --muted-foreground, --border, --radius) written by the design-spec
 * → globals.css chain, so every generated app's brand shows through
 * automatically — no per-app override needed.
 *
 * Two shapes:
 *   - `code` + `title` — error-family pages (404/403/500/503). Renders a
 *     large monogram (first letter of Document Intelligence on brand background)
 *     next to a code label + title.
 *   - `variant="loading"` — softer variant with pulsing monogram, used
 *     by app-level loading.tsx.
 */
export type EdgePageFrameProps = {
  code?: string;
  title: string;
  variant?: "error" | "loading";
  children?: React.ReactNode;
};

// Substituted by services.edge_page_customizer per-app. Kept as a
// static string here so the template lints without a config file.
const APP_INITIAL = "D";
const APP_NAME_LABEL = "Document Intelligence";

export function EdgePageFrame({ code, title, variant, children }: EdgePageFrameProps) {
  const isLoading = variant === "loading";
  return (
    <main className="edge-root" data-variant={variant ?? "error"}>
      <div className="edge-card">
        <div className={`edge-monogram${isLoading ? " edge-monogram--pulse" : ""}`}
             aria-hidden="true">
          {APP_INITIAL || APP_NAME_LABEL.slice(0, 1) || "•"}
        </div>
        {code && <div className="edge-code" aria-hidden="true">{code}</div>}
        <h1 className="edge-title">{title}</h1>
        <div className="edge-body">{children}</div>
      </div>
    </main>
  );
}
