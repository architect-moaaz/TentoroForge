import * as React from "react";
import "./EdgePageFrame.css";
import { BrandMark, BRAND_LOGO } from "@/components/BrandMark";

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
 *   - `code` + `title` — error-family pages (404/403/500/503). Renders the
 *     owner's logo when they gave one, and otherwise the large monogram
 *     (first letter of {{app_name}} on brand background) it has always
 *     drawn, next to a code label + title.
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
const APP_INITIAL = "{{app_initial}}";
const APP_NAME_LABEL = "{{app_name}}";

export function EdgePageFrame({ code, title, variant, children }: EdgePageFrameProps) {
  const isLoading = variant === "loading";
  return (
    // `data-forge-page-state` says which edge page this is ("404", "500", …) in
    // a form a check can read: with a `loading.tsx` streaming the response, a
    // not-found page is sent as HTTP 200, so the status alone cannot say it.
    <main className="edge-root" data-variant={variant ?? "error"} data-forge-page-state={code ?? variant ?? "error"}>
      <div className="edge-card">
        {/* These pages are the ones a visitor reaches with no session and no
            shell around them, so they are where an application most needs to
            look like itself. The monogram was always a stand-in for a mark
            nobody could supply; it stays for the applications that still have
            none. `aria-hidden` on the letter because it says nothing a screen
            reader wants — the mark carries its own alt text and does. */}
        {BRAND_LOGO ? (
          <BrandMark height={56}
                     className={`edge-mark${isLoading ? " edge-mark--pulse" : ""}`} />
        ) : (
          <div className={`edge-monogram${isLoading ? " edge-monogram--pulse" : ""}`}
               aria-hidden="true">
            {APP_INITIAL || APP_NAME_LABEL.slice(0, 1) || "•"}
          </div>
        )}
        {code && <div className="edge-code" aria-hidden="true">{code}</div>}
        <h1 className="edge-title">{title}</h1>
        <div className="edge-body">{children}</div>
      </div>
    </main>
  );
}
