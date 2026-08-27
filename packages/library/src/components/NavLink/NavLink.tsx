"use client";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

// Prop-based approach: the library does not depend on Next.js at all.
// The foundation app (or any wrapper) passes currentPath from usePathname().
//
// Accepts two prop shapes:
//   - hand-authored / JSX:  href + children
//   - schema / Figma (post unifyLabelHref remap): label + navigate (+ className)

type Props = {
  href?: string;
  navigate?: string;
  label?: string;
  children?: ReactNode;
  /** Current pathname — passed by the foundation wrapper (e.g. from Next.js usePathname). */
  currentPath?: string;
  className?: string;
  style?: StyleSlotT;
};

export function NavLink({ href, navigate, label, children, currentPath = "", className, style }: Props) {
  const dest = href ?? navigate ?? "#";
  const content = children ?? label;
  const active = currentPath !== "" && currentPath === dest;
  // When a className is supplied (Figma styling), don't also emit inline
  // padding/radius — inline styles would override the Tailwind classes.
  const inlineStyle = className
    ? resolveStyle(style)
    : {
        display: "inline-block",
        padding: "0.375rem 0.75rem",
        borderRadius: "0.25rem",
        textDecoration: "none",
        fontWeight: active ? 600 : 400,
        ...resolveStyle(style),
      };
  return (
    <a
      href={dest}
      aria-current={active ? "page" : undefined}
      className={className}
      style={inlineStyle}
      {...useMotion(style?.motion)}
    >
      {content}
    </a>
  );
}
