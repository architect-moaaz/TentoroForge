import type { ReactNode, ElementType, CSSProperties } from "react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

const ALLOWED_BOX_TAGS = ["div", "section", "article", "aside", "header", "footer", "main", "nav"] as const;
type BoxTag = (typeof ALLOWED_BOX_TAGS)[number];

export function Box({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const raw = p.as ?? "div";
  const Tag: ElementType = (ALLOWED_BOX_TAGS as readonly string[]).includes(raw) ? (raw as BoxTag) : "div";
  const slotProps = applyStyleSlot(node.style);
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  const callerClass = typeof p.className === "string" ? p.className : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as CSSProperties : {};
  return (
    <Tag
      data-node-id={node.id}
      className={callerClass || undefined}
      style={{ ...resolveStyle(node.style), ...slotProps.style, ...callerStyle }}
      data-motion={slotProps["data-motion"]}
    >
      {children}
    </Tag>
  );
}
