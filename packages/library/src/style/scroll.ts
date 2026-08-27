/**
 * One statement of "wide content scrolls, it does not bleed".
 *
 * The bleed is a `min-width` problem before it is an `overflow` one. A grid or
 * flex child defaults to `min-width: auto` — it refuses to shrink below its
 * content — so a five-column table inside a one-third-width card does not
 * overflow itself, it makes the CARD wider and pushes the layout out of shape.
 * `min-w-0` is what permits the box to be narrower than what it holds;
 * `overflow-x-auto` is what makes the excess scroll instead of spill. Either
 * one alone still bleeds, which is why they live together in one constant
 * rather than being remembered separately at each call site.
 */
import type { CSSProperties } from "react";

export const SCROLL_X = "w-full min-w-0 overflow-x-auto";

/**
 * Shadows at the edges that appear ONLY when there is more to scroll to.
 *
 * macOS hides scrollbars until you scroll, so a column cut mid-cell reads as a
 * broken layout rather than as content continuing — the thing that looks like
 * "bleeding" even once it is properly contained.
 *
 * Four background layers do it with no JS and no stylesheet (the library's
 * `style/*.css` are not imported by generated apps, so inline is the only
 * delivery that actually arrives). Two solid `--card` layers are attached
 * `local`, so they travel with the content and slide away from an edge once
 * you scroll past it; two shadow layers underneath are attached `scroll`, so
 * they stay put and become visible exactly when the cover leaves. At rest,
 * both ends are covered and nothing shows.
 */
export function scrollEdgeStyle(surface = "var(--card)"): CSSProperties {
  return {
    backgroundImage: [
      `linear-gradient(to right, ${surface} 30%, transparent)`,
      `linear-gradient(to left, ${surface} 30%, transparent)`,
      "radial-gradient(farthest-side at 0 50%, rgb(0 0 0 / 0.10), transparent)",
      "radial-gradient(farthest-side at 100% 50%, rgb(0 0 0 / 0.10), transparent)",
    ].join(", "),
    backgroundPosition: "left center, right center, left center, right center",
    backgroundRepeat: "no-repeat",
    backgroundSize: "40px 100%, 40px 100%, 14px 100%, 14px 100%",
    backgroundAttachment: "local, local, scroll, scroll",
  };
}
