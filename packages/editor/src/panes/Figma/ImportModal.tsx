import { useState } from "react";
import { extractFromFigma, parseFigmaUrl } from "../../save/api";

export type ImportModalProps = {
  open: boolean;
  onClose: () => void;
  /** Called with the extracted schema and the user-supplied save path. */
  onImport: (schema: any, savePath: string) => void;
  /** Base URL for the API (passed through to extractFromFigma). */
  apiBaseUrl?: string;
};

type Status = "idle" | "extracting" | "ready" | "error";

/**
 * ImportModal — Import a Figma design node as a page schema.
 *
 * Triggered by Cmd+Shift+F (or Ctrl+Shift+F on Windows/Linux).
 * Shows a URL input, a save-path input, and an "Extract" button.
 * On success displays a JSON preview and a "Save as page" button.
 */
export function ImportModal({ open, onClose, onImport, apiBaseUrl = "" }: ImportModalProps) {
  const [url, setUrl] = useState("");
  const [savePath, setSavePath] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleExtract() {
    const parsed = parseFigmaUrl(url);
    if (!parsed) {
      setError("Invalid Figma URL — expected https://figma.com/design/<key>/…?node-id=…");
      setStatus("error");
      return;
    }
    setStatus("extracting");
    setError(null);
    setResult(null);
    try {
      const r = await extractFromFigma(parsed, apiBaseUrl);
      if (r.error) {
        setError(r.error);
        setStatus("error");
        return;
      }
      setResult(r);
      setStatus("ready");
    } catch (e: any) {
      setError(String(e));
      setStatus("error");
    }
  }

  function handleSave() {
    if (!result?.schema || !savePath) return;
    onImport(result.schema, savePath);
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Import from Figma"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 3000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 24,
          width: 560,
          maxWidth: "90vw",
          boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
        }}
      >
        <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>Import from Figma</h3>

        <label style={{ display: "block", fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
          Figma URL
        </label>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://figma.com/design/…?node-id=…"
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "6px 8px",
            border: "1px solid #d1d5db",
            borderRadius: 4,
            fontSize: 13,
          }}
          aria-label="Figma URL"
        />

        <label
          style={{ display: "block", fontSize: 12, fontWeight: 500, marginTop: 12, marginBottom: 4 }}
        >
          Save as
        </label>
        <input
          value={savePath}
          onChange={(e) => setSavePath(e.target.value)}
          placeholder="products/imported"
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "6px 8px",
            border: "1px solid #d1d5db",
            borderRadius: 4,
            fontSize: 13,
          }}
          aria-label="Save path"
        />

        {status === "extracting" && (
          <p style={{ marginTop: 12, fontSize: 13, color: "#6b7280" }}>Extracting…</p>
        )}

        {error && (
          <p role="alert" style={{ marginTop: 12, fontSize: 13, color: "#dc2626" }}>
            {error}
          </p>
        )}

        {status === "ready" && result?.schema && (
          <>
            <p style={{ marginTop: 12, fontSize: 12, color: "#16a34a", fontWeight: 500 }}>
              Extracted successfully
            </p>
            <pre
              style={{
                maxHeight: 180,
                overflow: "auto",
                background: "#f3f4f6",
                padding: 8,
                fontSize: 11,
                borderRadius: 4,
                margin: "4px 0 0",
              }}
            >
              {JSON.stringify(result.schema, null, 2)}
            </pre>
          </>
        )}

        <div
          style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}
        >
          <button onClick={onClose} style={{ padding: "6px 14px", borderRadius: 4, cursor: "pointer" }}>
            Cancel
          </button>

          {status !== "ready" && (
            <button
              onClick={handleExtract}
              disabled={!url.trim() || status === "extracting"}
              style={{
                padding: "6px 14px",
                background: "#2563eb",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                cursor: !url.trim() || status === "extracting" ? "not-allowed" : "pointer",
                opacity: !url.trim() || status === "extracting" ? 0.6 : 1,
              }}
            >
              Extract
            </button>
          )}

          {status === "ready" && (
            <button
              onClick={handleSave}
              disabled={!savePath.trim()}
              style={{
                padding: "6px 14px",
                background: "#16a34a",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                cursor: !savePath.trim() ? "not-allowed" : "pointer",
                opacity: !savePath.trim() ? 0.6 : 1,
              }}
            >
              Save as page
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
