import type { ReactNode, CSSProperties } from "react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";
import { NavigateSurface } from "../../client/NavigateSurface";

/**
 * Container — centers its content with a responsive max-width and
 * breakpoint-scaled horizontal padding, so pages keep margins on phones
 * (where edge-to-edge content looks cramped) but expand to the configured
 * width on larger screens.
 */
const MAXW: Record<string, string> = {
  sm:  "max-w-screen-sm",
  md:  "max-w-screen-md",
  lg:  "max-w-screen-lg",
  xl:  "max-w-screen-xl",
  "2xl": "max-w-screen-2xl",
  full: "",
};

/**
 * THE SIX PROPS THE REGISTRY ADVERTISED AND THIS COMPONENT IGNORED.
 *
 * The registry describes Container as a "Flex layout container" with
 * direction / gap / padding / align / justify / wrap, and the editor renders a
 * live control for each. None was read: the component consumed only `maxWidth`,
 * so a user could set direction to horizontal, watch it save, and see nothing.
 *
 * Scales are borrowed from Stack rather than invented, so the two layout
 * primitives cannot drift into meaning different things by the same name.
 *
 * Blast radius was measured before turning these on: 0 of 26 Container nodes in
 * the projects on disk carry any of these props, so no existing page changes.
 * Only nodes dropped from here on — which DO get registry defaults seeded by
 * buildDroppedNode — will lay out as the contract says they should.
 */
const GAP_CLASS: Record<string, string> = {
  none: "gap-0", xs: "gap-1", sm: "gap-2", md: "gap-4", lg: "gap-6", xl: "gap-8",
};
const PAD_CLASS: Record<string, string> = {
  none: "p-0", xs: "p-1", sm: "p-2", md: "p-4", lg: "p-6", xl: "p-8",
};
const ALIGN_CLASS: Record<string, string> = {
  start: "items-start", center: "items-center", end: "items-end", stretch: "items-stretch",
};
const JUSTIFY_CLASS: Record<string, string> = {
  start: "justify-start", center: "justify-center", end: "justify-end",
  between: "justify-between", around: "justify-around", evenly: "justify-evenly",
};

export function Container({ node, children }: { node: any; children: ReactNode[] }) {
  const slotProps = applyStyleSlot(node.style);
  const maxKey = node.props?.maxWidth ?? "lg";
  const maxClass = MAXW[maxKey] ?? "max-w-screen-lg";
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  // When the caller supplies a className, treat the node as a styled passthrough
  // box: emit ONLY that className. The responsive page-container defaults
  // (mx-auto, max-w-screen-lg, breakpoint padding, w-full) would otherwise
  // force width:100% and collide with caller sizing like size-[56px].
  const callerClass = typeof node.props?.className === "string" ? node.props.className : "";
  const callerStyle = node.props?.style && typeof node.props.style === "object" ? node.props.style as CSSProperties : {};
  // Flex is opt-in: only a node that actually carries one of the layout props
  // becomes a flex container. A Container with none of them keeps the exact
  // page-wrapper rendering it has always had, so nothing on disk moves.
  const p = node.props ?? {};
  const wantsFlex = ["direction", "gap", "align", "justify", "wrap"]
    .some((k) => p[k] !== undefined);

  const flexParts: string[] = [];
  if (wantsFlex) {
    flexParts.push("flex", p.direction === "horizontal" ? "flex-row" : "flex-col");
    if (p.gap !== undefined) flexParts.push(GAP_CLASS[p.gap] ?? "gap-4");
    if (p.align !== undefined) flexParts.push(ALIGN_CLASS[p.align] ?? "items-start");
    if (p.justify !== undefined) flexParts.push(JUSTIFY_CLASS[p.justify] ?? "justify-start");
    if (p.wrap === true) flexParts.push("flex-wrap");
  }
  // An explicit padding REPLACES the responsive page padding rather than adding
  // to it — otherwise `padding: "none"` would still render px-4 and read as broken.
  const padClass = p.padding !== undefined
    ? (PAD_CLASS[p.padding] ?? "p-4")
    : "px-4 sm:px-6 lg:px-8";

  const className = callerClass
    ? callerClass
    : `mx-auto w-full ${padClass} ${maxClass} ${flexParts.join(" ")}`.replace(/\s+/g, " ").trim();
  // Same shellRole hook as Stack — LLM-generated shells often use Container
  // (not Stack) for the sidebar wrapper, so both need to forward the marker.
  const shellRole = node.props?.shellRole;
  const shellRoleAttr = (shellRole === "sidebar") ? "" : undefined;
  const backdropAttr = (shellRole === "backdrop") ? "" : undefined;
  // A container that navigates is a drawn card the designer made clickable:
  // same box, same classes, plus the affordance and the Navigator seam.
  if (typeof node.props?.navigate === "string" && node.props.navigate) {
    return (
      <NavigateSurface
        navigate={node.props.navigate}
        data-node-id={node.id}
        className={className}
        style={{
          ...resolveStyle(node.style),
          ...slotProps.style,
          ...callerStyle,
        }}
        data-motion={slotProps["data-motion"]}
        data-shell-sidebar={shellRoleAttr}
        data-sidebar-backdrop={backdropAttr}
      >
        {children}
      </NavigateSurface>
    );
  }
  return (
    <div
      data-node-id={node.id}
      className={className}
      style={{
        ...resolveStyle(node.style),
        ...slotProps.style,
        ...callerStyle,
      }}
      data-motion={slotProps["data-motion"]}
      data-shell-sidebar={shellRoleAttr}
      data-sidebar-backdrop={backdropAttr}
    >
      {children}
    </div>
  );
}
