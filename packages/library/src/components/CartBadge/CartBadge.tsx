"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CartBadgePropsType } from "./CartBadge.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CartBadgeProps extends CartBadgePropsType {
  style?: StyleSlotT;
}

/**
 * Live cart-count indicator. Polls once on mount, refreshes on the
 * `forge-cart-changed` window event fired by AddToCart / cart controls.
 *
 * IT ALWAYS PUTS A BOX ON THE SCREEN.
 * ----------------------------------
 * This used to `return null` whenever the count was not a number — which is
 * every render before the first fetch resolves, every 401, every network
 * error, and *every render on the editor canvas*, where there is no
 * `/api/cart` to answer at all. A dropped CartBadge therefore had
 * `childElementCount === 0` and a 0x0 rect: nothing to see, nothing to click,
 * nothing to select, and (because the empty-node hint overlay skips boxes
 * under 24x12) not even a hint saying it was there. The user got no signal
 * that the drop had worked.
 *
 * So an unknown count renders as a dimmed `0` rather than as nothing. That is
 * also the honest thing to show a signed-out visitor: an empty cart. The only
 * remaining way to render nothing is the one the author asked for —
 * `hideZero` with a count we actually fetched and that really is zero.
 *
 * The hook order matters too: `useMotion` used to be called BELOW the
 * `return null` guards, so the number of hooks this component ran changed with
 * the fetch result — a React rules-of-hooks violation that only stayed quiet
 * because the early return happened on the first render as well.
 */
export function CartBadge({ href = "/cart", label = "Cart", hideZero, className, style }: CartBadgeProps) {
  const [count, setCount] = React.useState<number | null>(null);
  const motionProps = useMotion(style?.motion);

  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch("/api/cart", { cache: "no-store" });
      if (!res.ok) {
        setCount(null);
        return;
      }
      const body = await res.json();
      setCount(typeof body?.count === "number" ? body.count : 0);
    } catch {
      setCount(null);
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const handler = () => refresh();
    window.addEventListener("forge-cart-changed", handler);
    return () => window.removeEventListener("forge-cart-changed", handler);
  }, [refresh]);

  // `hideZero` is a statement about a KNOWN empty cart. An unknown count is
  // not a zero, so it must not trigger the hide — otherwise the badge
  // disappears on the canvas and on every slow first paint.
  if (hideZero && count === 0) return null;

  const known = count != null;
  const shown = count ?? 0;

  return (
    <a
      href={href}
      data-cart-badge=""
      data-cart-count-known={known ? "true" : "false"}
      style={resolveStyle(style)}
      {...motionProps}
      className={[
        "inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-foreground hover:bg-accent",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      <span aria-hidden>🛒</span>
      <span>{label}</span>
      <span
        className={[
          "inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-xs font-semibold",
          known
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        ].join(" ")}
        aria-label={known ? `${shown} items` : "Cart count unavailable"}
      >
        {shown}
      </span>
    </a>
  );
}
