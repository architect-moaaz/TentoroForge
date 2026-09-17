import type * as React from "react";
import { BRAND_LOGO } from "@/contracts/brand";

/**
 * The owner's logo, wherever this application signs its name.
 *
 * Every screen that says which app you are looking at drew a LETTER — the
 * rail's rounded square, the sign-in lockup, the error pages' monogram. Each
 * one was a stand-in for a mark nobody could supply, because the Blueprint had
 * no field for an image. `designSystem.logo` is that field, and this is what
 * the chrome-less pages render it with. (The rail has its own copy inside the
 * component library, fed the same values from `shell.json`.)
 *
 * WHAT THIS DOES NOT DO is decide the fallback. A caller that has no mark keeps
 * drawing exactly what it drew before — the gradient square on sign-in, the big
 * monogram on a 404 — because those are four different designs of the same
 * idea and collapsing them into one would change four screens to add a feature
 * to none of them. So the shape at a call site is:
 *
 *     {BRAND_LOGO ? <BrandMark height={36} /> : <span className="…">{initial}</span>}
 *
 * Sized by HEIGHT, never squeezed into a square: a wordmark is several times
 * wider than it is tall, and `aspect` is what keeps an SVG with no intrinsic
 * width from laying out at zero.
 */
export function BrandMark({
  height = 36,
  alt,
  className,
  style,
}: {
  height?: number;
  /** Overrides the alt text the owner gave. Rarely right. */
  alt?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  if (!BRAND_LOGO) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={BRAND_LOGO.src}
      alt={alt ?? BRAND_LOGO.alt}
      className={className}
      style={{
        display: "block",
        height,
        width: BRAND_LOGO.aspect ? Math.round(height * BRAND_LOGO.aspect) : "auto",
        maxWidth: "100%",
        objectFit: "contain",
        ...style,
      }}
    />
  );
}

export { BRAND_LOGO };
