import { useState, type ReactNode } from "react";
import DOMPurify from "isomorphic-dompurify";

export type CustomEditorNode = {
  id: string;
  props?: {
    html?: string;
    tailwind?: string;
    label?: string;
  };
};

export type CustomEditorSavePayload = {
  html: string;
  tailwind: string;
  label?: string;
};

export type CustomEditorProps = {
  node: CustomEditorNode;
  onSave: (next: CustomEditorSavePayload) => void;
  onCancel: () => void;
};

export function CustomEditor({ node, onSave, onCancel }: CustomEditorProps): ReactNode {
  const initialProps = node.props ?? {};
  const [html, setHtml] = useState<string>(
    typeof initialProps.html === "string" ? initialProps.html : ""
  );
  const [tailwind, setTailwind] = useState<string>(
    typeof initialProps.tailwind === "string" ? initialProps.tailwind : ""
  );
  const [label, setLabel] = useState<string>(
    typeof initialProps.label === "string" ? initialProps.label : ""
  );

  const sanitizedPreview = DOMPurify.sanitize(html);

  function handleSave() {
    onSave({ html, tailwind, label: label || undefined });
  }

  return (
    <div
      data-custom-editor
      role="dialog"
      aria-modal="true"
      aria-labelledby="custom-editor-title"
      style={{
        width: 480,
        borderLeft: "1px solid #e5e7eb",
        background: "hsl(var(--background, 0 0% 100%))",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "8px 12px",
          borderBottom: "1px solid #e5e7eb",
          gap: 8,
        }}
      >
        <h2
          id="custom-editor-title"
          style={{ fontSize: 13, fontWeight: 600, flex: 1, margin: 0 }}
        >
          Edit Custom Block
        </h2>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Close custom editor"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 16,
            lineHeight: 1,
            color: "#6b7280",
            padding: "2px 4px",
          }}
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px 0" }}>
        {/* Label input */}
        <div style={{ marginBottom: 12 }}>
          <label
            htmlFor="custom-editor-label"
            style={{ display: "block", fontSize: 12, fontWeight: 500, marginBottom: 4, color: "#374151" }}
          >
            Label (shown on the canvas chip)
          </label>
          <input
            id="custom-editor-label"
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Custom"
            style={{
              width: "100%",
              boxSizing: "border-box",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              padding: "6px 8px",
              fontSize: 13,
              outline: "none",
            }}
          />
        </div>

        {/* HTML textarea */}
        <div style={{ marginBottom: 12 }}>
          <label
            htmlFor="custom-editor-html"
            style={{ display: "block", fontSize: 12, fontWeight: 500, marginBottom: 4, color: "#374151" }}
          >
            HTML
          </label>
          <textarea
            id="custom-editor-html"
            rows={12}
            value={html}
            onChange={(e) => setHtml(e.target.value)}
            placeholder="<div>Your custom HTML here…</div>"
            style={{
              width: "100%",
              boxSizing: "border-box",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              padding: "6px 8px",
              fontSize: 12,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              resize: "vertical",
              outline: "none",
            }}
          />
        </div>

        {/* Tailwind classes input */}
        <div style={{ marginBottom: 12 }}>
          <label
            htmlFor="custom-editor-tailwind"
            style={{ display: "block", fontSize: 12, fontWeight: 500, marginBottom: 4, color: "#374151" }}
          >
            Tailwind classes
          </label>
          <input
            id="custom-editor-tailwind"
            type="text"
            value={tailwind}
            onChange={(e) => setTailwind(e.target.value)}
            placeholder="p-4 rounded bg-white"
            style={{
              width: "100%",
              boxSizing: "border-box",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              padding: "6px 8px",
              fontSize: 13,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              outline: "none",
            }}
          />
        </div>

        {/* Preview */}
        <div style={{ marginBottom: 12 }}>
          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 4, color: "#374151", margin: "0 0 4px 0" }}>
            Preview
          </p>
          <div
            className={tailwind || undefined}
            dangerouslySetInnerHTML={{ __html: sanitizedPreview }}
            style={{
              maxHeight: 240,
              overflowY: "auto",
              border: "1px solid #e5e7eb",
              borderRadius: 4,
              padding: sanitizedPreview ? 8 : 0,
              background: "#fafafa",
              minHeight: 40,
            }}
          />
        </div>
      </div>

      {/* Footer */}
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: 8,
          padding: "8px 12px",
          borderTop: "1px solid #e5e7eb",
        }}
      >
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: "6px 14px",
            fontSize: 13,
            borderRadius: 4,
            border: "1px solid #d1d5db",
            background: "white",
            cursor: "pointer",
            color: "#374151",
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          style={{
            padding: "6px 14px",
            fontSize: 13,
            borderRadius: 4,
            border: "none",
            background: "#0f172a",
            color: "white",
            cursor: "pointer",
            fontWeight: 500,
          }}
        >
          Save
        </button>
      </div>
    </div>
  );
}
