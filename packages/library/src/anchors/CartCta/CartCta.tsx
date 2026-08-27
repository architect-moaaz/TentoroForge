"use client";
import * as React from "react";
import { z } from "zod";

/**
 * CartCta — the shopper equivalent of StickyPrimaryCta. Persistent
 * cart affordance pinned bottom-right with item count + subtotal. Not
 * the CartBadge in the shell nav — this is the deliberate "click here
 * to check out" pressure moment on the home surface.
 */
export const CartCtaProps = z.object({
  label: z.string().optional(),        // "View cart"
  count: z.number().int().nonnegative().optional(),
  subtotal: z.string().optional(),     // "$248.00"
  navigate: z.string().optional(),
  position: z.enum(["bottom-right", "bottom-center", "bottom-left"]).optional(),
});
export type CartCtaPropsType = z.infer<typeof CartCtaProps>;

const POS: Record<string, string> = {
  "bottom-right":  "bottom-6 right-6",
  "bottom-center": "bottom-6 left-1/2 -translate-x-1/2",
  "bottom-left":   "bottom-6 left-6",
};

export function CartCta({ label, count, subtotal, navigate, position = "bottom-right" }: CartCtaPropsType) {
  if (!label && !count && !subtotal) return null;
  return (
    <a
      href={navigate || "/cart"}
      data-anchor="cart_cta"
      className={`fixed z-40 inline-flex items-center gap-3 h-14 pl-4 pr-5 rounded-full bg-primary text-primary-foreground shadow-lg hover:brightness-110 transition ${POS[position]}`}
    >
      <span className="relative grid place-items-center h-8 w-8 rounded-full bg-white/15" aria-hidden="true">
        🛍
        {typeof count === "number" && count > 0 && (
          <span className="absolute -top-1 -right-1 h-5 min-w-5 px-1 rounded-full bg-white text-[10px] font-bold text-primary grid place-items-center">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-sm font-semibold">{label || "View cart"}</span>
        {subtotal && <span className="text-[11px] opacity-90 tabular-nums">{subtotal}</span>}
      </span>
    </a>
  );
}
