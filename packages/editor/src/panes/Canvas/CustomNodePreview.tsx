import type { ReactNode } from "react";
import DOMPurify from "isomorphic-dompurify";

export type CustomNodePreviewProps = {
  node: {
    id: string;
    props?: {
      html?: string;
      tailwind?: string;
      label?: string;
    };
  };
  onEdit?: () => void;
};

export function CustomNodePreview({ node, onEdit }: CustomNodePreviewProps): ReactNode {
  const props = node.props ?? {};
  const rawHtml = typeof props.html === "string" ? props.html : "";
  const sanitized = DOMPurify.sanitize(rawHtml);
  const tailwind = typeof props.tailwind === "string" ? props.tailwind : "";
  const label = typeof props.label === "string" && props.label ? props.label : "Custom";

  const wrapperClassName = ["custom-block", tailwind].filter(Boolean).join(" ");

  return (
    <div
      data-node-id={node.id}
      data-custom-preview
      className={wrapperClassName || undefined}
      style={{ position: "relative" }}
    >
      {rawHtml ? (
        <div
          style={{ pointerEvents: "none" }}
          dangerouslySetInnerHTML={{ __html: sanitized }}
        />
      ) : (
        <div
          style={{
            pointerEvents: "none",
            padding: 24,
            color: "#94a3b8",
            fontStyle: "italic",
            textAlign: "center",
          }}
        >
          Empty Custom block — click &quot;Edit&quot; to add content
        </div>
      )}
      {/* Floating chip in top-right corner */}
      <div
        role="button"
        tabIndex={0}
        aria-label={`Edit ${label} block`}
        onClick={() => onEdit?.()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onEdit?.(); }}
        style={{
          position: "absolute",
          top: 4,
          right: 4,
          fontSize: 11,
          padding: "2px 6px",
          borderRadius: 4,
          background: "#0f172a",
          color: "white",
          cursor: "pointer",
          zIndex: 1,
          userSelect: "none",
        }}
      >
        {label} Edit
      </div>
    </div>
  );
}
