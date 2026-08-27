import * as React from "react";

export interface IllustrationResolverProps {
  /** unDraw slug (or custom slug bundled into the project) */
  slug: string;
  /** Accessible alt text — required for non-decorative illustrations */
  alt: string;
  /** Override the asset base path. Defaults to /illustrations (Next.js public/) */
  basePath?: string;
  /** Optional max width/height in CSS units */
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Renders an illustration bundled at <basePath>/<slug>.svg.
 *
 * For the standalone generated app: basePath defaults to /illustrations
 * (served from public/ by Next.js).
 *
 * For the render-scaffold preview: caller passes basePath like
 * "/p/<projectId>/illustrations" so the scaffold's backend route can
 * resolve to output/<projectId>/public/illustrations/<slug>.svg.
 */
export function IllustrationResolver({
  slug,
  alt,
  basePath = "/illustrations",
  width,
  height,
  className,
  style,
}: IllustrationResolverProps) {
  if (!slug) return null;
  const src = `${basePath.replace(/\/$/, "")}/${slug}.svg`;
  return (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      className={className}
      style={style}
      loading="lazy"
    />
  );
}
