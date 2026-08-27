import { useState } from "react";
import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectCurrentPage } from "../../state/selectors";
import { regenerateSection } from "../../save/api";
import { Nodes } from "@tentoroforge/schema";
import { renderNode, type DispatchContext } from "@tentoroforge/renderer";
import {
  findNodeDeep,
  findParentId,
  findIndexInParent,
  buildRemoveNode,
  buildInsertNode,
} from "../../state/mutations";

// Minimal mock DispatchContext for read-only diff rendering
// registry.has() must return false so renderNode falls through to built-in types
const mockCtx: DispatchContext = {
  data: {},
  registry: { has: () => false, get: () => undefined, validateProps: () => ({}) },
} as any;

// Safe render with JSON fallback when renderer can't handle the type
function safeRenderNode(node: any): React.ReactNode {
  try {
    return renderNode(node, mockCtx);
  } catch {
    return <pre style={{ fontSize: 11, margin: 0, overflow: "auto" }}>{JSON.stringify(node, null, 2)}</pre>;
  }
}

// Store-based props (original API)
type StoreModeProps = {
  store: EditorStoreApi;
  nodeId: string;
  apiBaseUrl?: string;
  onClose: () => void;
  // standalone props must be absent
  open?: undefined;
  subtree?: undefined;
  onAccept?: undefined;
};

// Standalone props (new test-friendly API)
type StandaloneModeProps = {
  open: boolean;
  onClose: () => void;
  subtree: any;
  onAccept: (proposed: any) => void;
  // store-mode props must be absent
  store?: undefined;
  nodeId?: undefined;
  apiBaseUrl?: string;
};

export type RegenerateModalProps = StoreModeProps | StandaloneModeProps;

export function RegenerateModal(props: RegenerateModalProps) {
  if (props.store !== undefined) {
    return <StoreModeModal {...(props as StoreModeProps)} />;
  }
  return <StandaloneModeModal {...(props as StandaloneModeProps)} />;
}

// ---- Store-based (original) implementation ----

function StoreModeModal({ store, nodeId, apiBaseUrl = "", onClose }: StoreModeProps) {
  const page = useStore(store, selectCurrentPage);
  const [promptText, setPromptText] = useState("");
  const [status, setStatus] = useState<"idle" | "thinking" | "done" | "error">("idle");
  const [proposedSubtree, setProposedSubtree] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [isValid, setIsValid] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  if (!page) return null;

  const node = findNodeDeep(page.schema.root, nodeId);
  const nodeType = node?.type ?? "unknown";

  async function handleRegenerate() {
    if (!promptText.trim()) return;
    setStatus("thinking");
    setProposedSubtree(null);
    setErrorMsg("");
    setIsValid(false);
    setValidationError(null);
    try {
      const result = await regenerateSection(promptText.trim(), node, apiBaseUrl);
      const proposed = result.subtree;
      const validation = Nodes.Node.safeParse(proposed);
      setProposedSubtree(proposed);
      setIsValid(validation.success);
      setValidationError(
        validation.success
          ? null
          : validation.error.errors.map((e: any) => e.message).join("; ")
      );
      setStatus("done");
    } catch (e: any) {
      setErrorMsg(e?.message ?? "Unknown error");
      setStatus("error");
    }
  }

  function handleAccept() {
    if (!proposedSubtree || !page || !isValid) return;

    const root = page.schema.root;
    const parentId = findParentId(root, nodeId);
    if (!parentId) {
      onClose();
      return;
    }
    const index = findIndexInParent(root, nodeId);
    const removeM = buildRemoveNode(nodeId, page.schema);
    const insertM = buildInsertNode(parentId, index, proposedSubtree);
    store.getState().apply({
      kind: "composite",
      mutations: [removeM, insertM],
    });
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Regenerate section"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 24,
          width: 720,
          maxWidth: "90vw",
          boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
        }}
      >
        <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600 }}>Regenerate section</h2>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "#6b7280" }}>
          Selected: <strong>{nodeType}</strong> <code style={{ fontSize: 11 }}>#{nodeId}</code>
        </p>

        <textarea
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
          placeholder="e.g. Make this look more like a Stripe-style header"
          rows={4}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "8px 10px",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            fontSize: 13,
            resize: "vertical",
          }}
          aria-label="Regenerate prompt"
        />

        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={onClose} style={{ flex: 1, padding: "6px 12px" }}>
            Cancel
          </button>
          <button
            onClick={handleRegenerate}
            disabled={!promptText.trim() || status === "thinking"}
            style={{
              flex: 2,
              padding: "6px 12px",
              background: "#2563eb",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: promptText.trim() && status !== "thinking" ? "pointer" : "not-allowed",
              opacity: !promptText.trim() || status === "thinking" ? 0.6 : 1,
            }}
          >
            {status === "thinking" ? "Thinking…" : "Regenerate"}
          </button>
        </div>

        {status === "thinking" && (
          <p style={{ marginTop: 12, fontSize: 13, color: "#6b7280", textAlign: "center" }}>
            Thinking…
          </p>
        )}

        {status === "error" && (
          <p style={{ marginTop: 12, fontSize: 13, color: "#dc2626" }}>
            Error: {errorMsg}
          </p>
        )}

        {status === "done" && proposedSubtree && (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13 }}>Before</h4>
                <div data-diff-before style={{ border: "1px solid #e5e7eb", borderRadius: 4, padding: 8, minHeight: 60, background: "#f9fafb" }}>
                  {node ? safeRenderNode(node) : null}
                </div>
              </div>
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13 }}>After</h4>
                <div data-diff-after style={{ border: "1px solid #e5e7eb", borderRadius: 4, padding: 8, minHeight: 60, background: "#f9fafb" }}>
                  {isValid
                    ? safeRenderNode(proposedSubtree)
                    : <pre style={{ fontSize: 11, margin: 0, overflow: "auto" }}>{JSON.stringify(proposedSubtree, null, 2)}</pre>
                  }
                </div>
              </div>
            </div>
            {validationError && (
              <div role="alert" style={{ color: "#dc2626", marginTop: 8, fontSize: 12 }}>
                Invalid subtree: {validationError}
              </div>
            )}
            <button
              onClick={handleAccept}
              disabled={!isValid}
              style={{
                width: "100%",
                marginTop: 12,
                padding: "8px 12px",
                background: isValid ? "#16a34a" : "#9ca3af",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: isValid ? "pointer" : "not-allowed",
                fontWeight: 600,
              }}
              aria-label="Accept regenerated subtree"
            >
              Accept
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- Standalone (test-friendly) implementation ----

function StandaloneModeModal({ open, onClose, subtree, onAccept, apiBaseUrl = "" }: StandaloneModeProps) {
  const [promptText, setPromptText] = useState("");
  const [status, setStatus] = useState<"idle" | "thinking" | "done" | "error">("idle");
  const [proposedSubtree, setProposedSubtree] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [isValid, setIsValid] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  if (!open) return null;

  async function handleRegenerate() {
    if (!promptText.trim()) return;
    setStatus("thinking");
    setProposedSubtree(null);
    setErrorMsg("");
    setIsValid(false);
    setValidationError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/editor/suggest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText.trim(), subtree }),
      });
      const data = await res.json();
      const proposed = data.subtree;
      const validation = Nodes.Node.safeParse(proposed);
      setProposedSubtree(proposed);
      setIsValid(validation.success);
      setValidationError(
        validation.success
          ? null
          : validation.error.errors.map((e: any) => e.message).join("; ")
      );
      setStatus("done");
    } catch (e: any) {
      setErrorMsg(e?.message ?? "Unknown error");
      setStatus("error");
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Regenerate section"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 24,
          width: 720,
          maxWidth: "90vw",
          boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
        }}
      >
        <h2 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>Regenerate section</h2>

        <textarea
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
          placeholder="Describe what you want to change…"
          rows={3}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "8px 10px",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            fontSize: 13,
            resize: "vertical",
          }}
          aria-label="Regenerate prompt"
        />

        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={onClose} style={{ flex: 1, padding: "6px 12px" }}>
            Cancel
          </button>
          <button
            onClick={handleRegenerate}
            disabled={!promptText.trim() || status === "thinking"}
            style={{
              flex: 2,
              padding: "6px 12px",
              background: "#2563eb",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: promptText.trim() && status !== "thinking" ? "pointer" : "not-allowed",
              opacity: !promptText.trim() || status === "thinking" ? 0.6 : 1,
            }}
          >
            {status === "thinking" ? "Thinking…" : "Regenerate"}
          </button>
        </div>

        {status === "error" && (
          <p style={{ marginTop: 12, fontSize: 13, color: "#dc2626" }}>
            Error: {errorMsg}
          </p>
        )}

        {status === "done" && proposedSubtree && (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13 }}>Before</h4>
                <div data-diff-before style={{ border: "1px solid #e5e7eb", borderRadius: 4, padding: 8, minHeight: 60, background: "#f9fafb" }}>
                  {safeRenderNode(subtree)}
                </div>
              </div>
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13 }}>After</h4>
                <div data-diff-after style={{ border: "1px solid #e5e7eb", borderRadius: 4, padding: 8, minHeight: 60, background: "#f9fafb" }}>
                  {isValid
                    ? safeRenderNode(proposedSubtree)
                    : <pre style={{ fontSize: 11, margin: 0, overflow: "auto" }}>{JSON.stringify(proposedSubtree, null, 2)}</pre>
                  }
                </div>
              </div>
            </div>
            {validationError && (
              <div role="alert" style={{ color: "#dc2626", marginTop: 8, fontSize: 12 }}>
                Invalid subtree: {validationError}
              </div>
            )}
            <button
              onClick={() => onAccept(proposedSubtree)}
              disabled={!isValid}
              style={{
                width: "100%",
                marginTop: 12,
                padding: "8px 12px",
                background: isValid ? "#16a34a" : "#9ca3af",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: isValid ? "pointer" : "not-allowed",
                fontWeight: 600,
              }}
              aria-label="Accept regenerated subtree"
            >
              Accept
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
