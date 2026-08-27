import * as React from "react";
import { z } from "zod";
import type { EmptyStateRichNode } from "@tentoroforge/schema";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";
import { IllustrationResolver } from "../surfaces/IllustrationResolver";

type Props = z.infer<typeof EmptyStateRichNode>["props"] & {
  /** Private prop injected by SchemaRendererWrapper to scope illustration
   * lookups to /p/<projectId>/illustrations under the preview scaffold. */
  __illustrationBasePath?: string;
};

export function EmptyStateRich({ icon, illustration, heading, body, primaryCta, sampleDataLink, __illustrationBasePath }: Props) {
  const radiusScale = useRadiusScale();
  // Illustration accepts either a bare URL string (legacy) or a structured
  // { slug, alt?, tone? } slot. Structured form is resolved via
  // IllustrationResolver to <basePath>/<slug>.svg.
  const illustrationIsSlot = !!illustration && typeof illustration === "object";
  const illustrationSrc = typeof illustration === "string" ? illustration : undefined;
  return (
    <div className={`flex flex-col items-center justify-center text-center px-6 py-12 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-dashed border-border bg-muted/20`}>
      {illustrationIsSlot && illustration && typeof illustration === "object" ? (
        <IllustrationResolver
          slug={illustration.slug}
          alt={illustration.alt ?? ""}
          basePath={__illustrationBasePath ?? "/illustrations"}
          className="mb-4 h-32 w-auto object-contain opacity-90"
        />
      ) : illustrationSrc ? (
        <img src={illustrationSrc} alt="" className="mb-4 h-32 w-32 object-contain opacity-80" aria-hidden="true" />
      ) : (
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
          <span className="text-3xl text-muted-foreground" data-icon={icon ?? "inbox"} aria-hidden="true">
            {icon === "calendar" ? "📅" :
             icon === "users" ? "👥" :
             icon === "file" ? "📄" :
             icon === "search" ? "🔍" :
             icon === "chart" ? "📊" :
             "📦"}
          </span>
        </div>
      )}
      <h3 className="text-lg font-semibold text-foreground mb-1">{heading}</h3>
      {body && (
        <p className="max-w-sm text-sm text-muted-foreground mb-5">{body}</p>
      )}
      {primaryCta && (
        <button
          type="button"
          className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          data-cta-action={
            primaryCta.action
              ? primaryCta.action.type === "navigate"
                ? `navigate:${primaryCta.action.to ?? ""}`
                : `workflow:${primaryCta.action.workflow ?? ""}`
              : undefined
          }
        >
          {primaryCta.label ?? "Action"}
        </button>
      )}
      {sampleDataLink && (() => {
        // Accept a bare URL string (→ a real link) or a structured { label, href,
        // action } CTA. Normalising here keeps the schema tolerant of both.
        const link = typeof sampleDataLink === "string" ? { href: sampleDataLink } : sampleDataLink;
        const cls = "mt-3 text-xs text-primary underline-offset-2 hover:underline";
        const text = link.label ?? "Sample data";
        return link.href ? (
          <a href={link.href} className={cls}>{text}</a>
        ) : (
          <button
            type="button"
            className={cls}
            data-cta-action={link.action ? `workflow:${link.action.workflow ?? ""}` : undefined}
          >
            {text}
          </button>
        );
      })()}
    </div>
  );
}
