import type { ReactNode, ComponentType, CSSProperties } from "react";
import type { DispatchContext } from "../../runtime/dispatch";

const SIZE_KEYS = ["width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight"] as const;

/**
 * Extract raw sizing from a node's StyleSlot, if any. Returned as CSS so the
 * dispatcher wrapper can carry it. Only sizing keys — padding/radius/background
 * stay on the component itself (it applies its own resolveStyle).
 */
function sizingFromStyle(style: unknown): CSSProperties | null {
  if (!style || typeof style !== "object") return null;
  const s = style as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  let has = false;
  for (const k of SIZE_KEYS) {
    if (s[k] !== undefined && s[k] !== "") { out[k] = s[k]; has = true; }
  }
  return has ? (out as CSSProperties) : null;
}

/**
 * LibraryDispatcher — renders a registered library component with already-validated props.
 *
 * Props are validated eagerly by `renderNode` before this component is called,
 * so errors surface at dispatch time (synchronously), not during React rendering.
 */
export function LibraryDispatcher({
  node,
  ctx,
  validatedProps,
  children,
}: {
  node: { id: string; type: string; props?: Record<string, unknown> };
  ctx: DispatchContext;
  /** Pre-validated, coerced props from registry.validateProps(). */
  validatedProps: Record<string, unknown>;
  children?: ReactNode;
}): ReactNode {
  const { registry } = ctx;

  if (!registry || !registry.has(node.type)) {
    throw new Error(
      `LibraryDispatcher: type '${node.type}' not found in registry`
    );
  }

  const entry = registry.get(node.type)!;
  const Component = (entry as { component: ComponentType<Record<string, unknown>> }).component;

  // When the node carries explicit sizing (width/height/min/max), the wrapper
  // must be a real box (not display:contents) so the size actually applies —
  // this makes sizing work uniformly for every library component (incl. Chart /
  // DataGrid that hardcode their own dimensions) and gives the node a drag/
  // measure box. display:contents is kept for un-sized nodes (zero layout change
  // for existing schemas, which never set node.style sizing).
  const sizing = sizingFromStyle((validatedProps as { style?: unknown }).style);
  if (sizing) {
    return (
      <span
        data-node-id={node.id}
        style={{ display: "block", boxSizing: "border-box", ...sizing }}
      >
        <Component {...validatedProps}>{children}</Component>
      </span>
    );
  }
  return (
    <span data-node-id={node.id} style={{ display: "contents" }}>
      <Component {...validatedProps}>{children}</Component>
    </span>
  );
}
