"use client";
import * as React from "react";
import { z } from "zod";

/**
 * StickyPrimaryCta — floating primary action pinned to the bottom-right of
 * the viewport. The one-thing-to-do on this page. Persistent while scrolling.
 * A member_home always has "book a class"; a shopper_home always has "cart".
 */
export const StickyPrimaryCtaProps = z.object({
  label: z.string().optional(),
  navigate: z.string().optional(),
  icon: z.string().optional(),      // emoji or icon name; render as-is for now
  position: z.enum(["bottom-right", "bottom-center", "bottom-left"]).optional(),
});
export type StickyPrimaryCtaPropsType = z.infer<typeof StickyPrimaryCtaProps>;

const POS: Record<string, string> = {
  "bottom-right":  "bottom-6 right-6",
  "bottom-center": "bottom-6 left-1/2 -translate-x-1/2",
  "bottom-left":   "bottom-6 left-6",
};

export function StickyPrimaryCta({ label, navigate, icon, position = "bottom-right" }: StickyPrimaryCtaPropsType) {
  if (!label) return null;
  return (
    <a
      href={navigate || "#"}
      data-anchor="sticky_primary_cta"
      className={`fixed z-40 inline-flex items-center gap-2 h-12 px-5 rounded-full bg-primary text-primary-foreground text-sm font-semibold shadow-lg hover:brightness-110 transition ${POS[position]}`}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {label}
    </a>
  );
}
