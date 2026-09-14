"use client";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";

// Prop-based approach: the library does not depend on Next.js at all.
// The foundation app (or any wrapper) passes currentPath from usePathname().
//
// Accepts two prop shapes:
//   - hand-authored / JSX:  href + children
//   - schema / Figma (post unifyLabelHref remap): label + navigate (+ className)

type Props = {
  href?: string;
  navigate?: string;
  /**
   * Third spelling of the destination. The registry declares `target`
   * ("Target page ID or external URL") and the editor renders a control for it,
   * but it was never in the fallback chain — so a user could type a destination,
   * watch it save, and get a link to "#". Same class as `icon` below.
   */
  target?: string;
  label?: string;
  /** Leading icon name, resolved through the shared icon map (as Button does). */
  icon?: string;
  children?: ReactNode;
  /** Current pathname — passed by the foundation wrapper (e.g. from Next.js usePathname). */
  currentPath?: string;
  className?: string;
  style?: StyleSlotT;
};

export function NavLink({ href, navigate, target, label, icon, children, currentPath = "", className, style }: Props) {
  const dest = href ?? navigate ?? target ?? "#";
  const IconComp = icon ? resolveIcon(icon) : null;
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
      {IconComp ? (
        <IconComp
          size={16}
          aria-hidden="true"
          style={{ display: "inline-block", verticalAlign: "-0.15em", marginInlineEnd: content ? "0.375rem" : 0 }}
        />
      ) : null}
      {content}
    </a>
  );
}
