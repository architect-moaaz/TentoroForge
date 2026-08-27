import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

export function Image({ node }: { node: any }) {
  const p = node.props ?? {};
  const { src, alt, width, height } = p;
  // No src → render nothing. The browser's broken-image icon + alt text
  // looks worse than an empty slot, and the deterministic Figma mapper
  // can emit Image / Icon nodes without resolved asset URLs.
  if (!src || typeof src !== "string") {
    return null;
  }
  const slotProps = applyStyleSlot(node.style);
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  const callerClass = typeof p.className === "string" ? p.className : undefined;
  return (
    <img
      data-node-id={node.id}
      src={src}
      alt={alt ?? ""}
      width={width}
      height={height}
      className={callerClass}
      style={{ ...resolveStyle(node.style), ...slotProps.style }}
      data-motion={slotProps["data-motion"]}
    />
  );
}
