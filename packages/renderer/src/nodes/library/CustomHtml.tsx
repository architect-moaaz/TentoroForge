"use client";
import * as React from "react";

/**
 * Renders sanitized raw HTML for the Custom escape-hatch node.
 *
 * Sanitization runs on the CLIENT with browser DOMPurify (imported lazily), so
 * the renderer never pulls the jsdom-backed `isomorphic-dompurify` — and its
 * ESM-only encoding sub-deps (html-encoding-sniffer / @exodus/bytes) that crash
 * a CJS server require — into every page's server bundle. The server render is
 * an empty shell that fills in on hydration; Custom is a rarely-used escape
 * hatch, so client-only sanitization is an acceptable trade for not loading
 * jsdom on every request.
 */
export function CustomHtml({
  html,
  nodeId,
  className,
  label,
  style,
  dataMotion,
}: {
  html: string;
  nodeId?: string;
  className?: string;
  label?: string;
  style?: React.CSSProperties;
  dataMotion?: string;
}) {
  const [safe, setSafe] = React.useState("");
  React.useEffect(() => {
    let alive = true;
    import("dompurify")
      .then((m) => {
        const DOMPurify = (m as { default?: { sanitize(s: string): string } }).default ?? (m as any);
        if (alive) setSafe(DOMPurify.sanitize(html ?? ""));
      })
      .catch(() => {
        if (alive) setSafe("");
      });
    return () => {
      alive = false;
    };
  }, [html]);

  return (
    <div
      data-node-id={nodeId}
      className={className || undefined}
      data-custom-label={label}
      style={style}
      data-motion={dataMotion}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}
