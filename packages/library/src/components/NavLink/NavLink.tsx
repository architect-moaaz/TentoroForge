"use client";
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";
import { pathMatchesRoute, currentBrowserPath } from "../../util/routeMatch";

// Prop-based approach: the library does not depend on Next.js at all.
// The foundation app (or any wrapper) may pass currentPath from usePathname();
// when it does not, the component reads the browser's own path (see below).
//
// Accepts three prop shapes, because three producers name the destination
// differently and all three reach this component:
//   - hand-authored / JSX:          href + children
//   - schema / Figma remap:         label + navigate (+ className)
//   - the component registry:       label + target (+ icon)
// `target` used to be accepted by NOBODY: the registry declares it, the editor
// writes it, and this component read only href/navigate — so every NavLink
// dropped from the palette rendered `href="#"` and went nowhere however the
// user filled the panel in. Same story for `icon`, declared and never rendered.

type Props = {
  href?: string;
  navigate?: string;
  /** Registry/editor name for the destination. Third alias, same meaning. */
  target?: string;
  label?: string;
  /** Leading icon name, resolved through the shared icon registry. */
  icon?: string;
  children?: ReactNode;
  /** Current pathname — passed by the foundation wrapper (e.g. from Next.js
   *  usePathname). Optional: falls back to the browser's own path. */
  currentPath?: string;
  className?: string;
  style?: StyleSlotT;
};

export function NavLink({
  href, navigate, target, label, icon, children, currentPath, className, style,
}: Props) {
  const dest = (href ?? navigate ?? target ?? "").trim();
  const content = children ?? label;
  const Icon = icon ? resolveIcon(icon) : null;

  // ACTIVE STATE WITHOUT A COOPERATING HOST.
  //
  // `aria-current` is the one thing a NavLink is for, and it never appeared:
  // `currentPath` defaulted to "" and only the generated app's shell ever
  // passed it, so in the preview renderer — and in any host that just drops a
  // NavLink on a page — no link was ever marked current. Read the path
  // ourselves when we are not told it. In an effect, not in render, so the
  // server-rendered markup and the first client paint agree.
  const [browserPath, setBrowserPath] = React.useState<string | undefined>(undefined);
  React.useEffect(() => {
    if (currentPath === undefined) setBrowserPath(currentBrowserPath());
  }, [currentPath]);
  const here = currentPath !== undefined && currentPath !== "" ? currentPath : browserPath;
  // Suffix match, not equality: the same page is served at "/items" in the
  // shipped app and "/p/<project>/items" in the preview. See util/routeMatch.
  const active = pathMatchesRoute(dest, here);

  // A nav item with no destination is not a link — same reasoning as Link:
  // `href="#"` looks and focuses exactly like a working nav item and does
  // nothing at all when activated.
  const inert = dest === "";

  // When a className is supplied (Figma styling), don't also emit inline
  // padding/radius — inline styles would override the Tailwind classes.
  const inlineStyle = className
    ? resolveStyle(style)
    : {
        display: "inline-flex",
        alignItems: "center",
        gap: "0.375rem",
        padding: "0.375rem 0.75rem",
        borderRadius: "0.25rem",
        textDecoration: "none",
        fontWeight: active ? 600 : 400,
        ...resolveStyle(style),
      };
  return (
    <a
      {...(inert ? { "data-navlink-unset": "", "aria-disabled": true } : { href: dest })}
      aria-current={active ? "page" : undefined}
      data-active={active ? "true" : undefined}
      className={className}
      style={inlineStyle}
      {...useMotion(style?.motion)}
    >
      {Icon && <Icon size={16} aria-hidden="true" />}
      {content}
    </a>
  );
}
