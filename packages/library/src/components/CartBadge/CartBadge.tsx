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
 * Silently renders nothing on 401 or when hideZero + count===0.
 */
export function CartBadge({ href = "/cart", label = "Cart", hideZero, className, style }: CartBadgeProps) {
  const [count, setCount] = React.useState<number | null>(null);

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

  if (count == null) return null;
  if (hideZero && count === 0) return null;

  return (
    <a
      href={href}
      data-cart-badge=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      className={[
        "inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-foreground hover:bg-accent",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      <span aria-hidden>🛒</span>
      <span>{label}</span>
      <span
        className="inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-xs font-semibold text-primary-foreground"
        aria-label={`${count} items`}
      >
        {count}
      </span>
    </a>
  );
}
