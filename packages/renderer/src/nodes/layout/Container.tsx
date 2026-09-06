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
  const className = callerClass
    ? callerClass
    : `mx-auto w-full px-4 sm:px-6 lg:px-8 ${maxClass}`;
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
