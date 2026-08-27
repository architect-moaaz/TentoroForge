"use client";
import { useState } from "react";
import { Smartphone, Tablet, Monitor, Undo2, Redo2, Sparkles, Eye, Loader2 } from "lucide-react";
import { useEditorStore, flushPersister } from "@/lib/editor-store";
import { ExportPanel } from "./ExportPanel";
import { AiPromptModal } from "./AiPromptModal";
import { PreviewModal } from "./PreviewModal";

type Device = "mobile" | "tablet" | "desktop";

// Empty string means "same origin" — on UAT the browser hits caddy on
// /p/... which routes to the render-scaffold container. Local dev sets
// NEXT_PUBLIC_PREVIEW_URL=http://localhost:6503 in .env.local to point
// at the standalone scaffold process.
const PREVIEW_BASE = process.env.NEXT_PUBLIC_PREVIEW_URL ?? "";

interface Props {
  projectId: string;
  device: Device;
  onDeviceChange: (d: Device) => void;
  isDirty?: boolean;
  onSave?: () => void;
  /** Current page slug — Preview opens the render-scaffold at this page. */
  currentPage?: string;
}

const ICON_BTN =
  "h-7 w-7 grid place-items-center rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors";
const ICON_BTN_ACTIVE =
  "h-7 w-7 grid place-items-center rounded bg-foreground text-background";

export function EditorToolbar({ projectId, device, onDeviceChange, isDirty = false, onSave, currentPage }: Props) {
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const canUndo = useEditorStore((s) => s.undoStack.length > 0);
  const canRedo = useEditorStore((s) => s.redoStack.length > 0);
  const [aiOpen, setAiOpen] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");

  return (
    <header className="h-10 px-2 flex items-center gap-0.5 bg-background border-b flex-shrink-0">
      {/* Device toggles */}
      <button
        onClick={() => onDeviceChange("mobile")}
        className={device === "mobile" ? ICON_BTN_ACTIVE : ICON_BTN}
        title="Mobile"
        aria-label="Mobile viewport"
      >
        <Smartphone size={16} />
      </button>
      <button
        onClick={() => onDeviceChange("tablet")}
        className={device === "tablet" ? ICON_BTN_ACTIVE : ICON_BTN}
        title="Tablet"
        aria-label="Tablet viewport"
      >
        <Tablet size={16} />
      </button>
      <button
        onClick={() => onDeviceChange("desktop")}
        className={device === "desktop" ? ICON_BTN_ACTIVE : ICON_BTN}
        title="Desktop"
        aria-label="Desktop viewport"
      >
        <Monitor size={16} />
      </button>

      <div className="w-px h-5 bg-border mx-1.5" />

      {/* Undo / Redo */}
      <button
        onClick={undo}
        disabled={!canUndo}
        className={ICON_BTN}
        title="Undo (Cmd+Z)"
        aria-label="Undo"
      >
        <Undo2 size={16} />
      </button>
      <button
        onClick={redo}
        disabled={!canRedo}
        className={ICON_BTN}
        title="Redo (Cmd+Shift+Z)"
        aria-label="Redo"
      >
        <Redo2 size={16} />
      </button>

      <div className="flex-1" />

      {/* Right cluster */}
      <button
        onClick={async () => {
          setPreviewing(true);
          try {
            await flushPersister();
          } catch (err) {
            console.warn("[EditorToolbar] flushPersister failed, opening preview anyway:", err);
          } finally {
            const slug = currentPage && currentPage !== "home" ? `/${currentPage}` : "";
            // Cache-bust via timestamp so the iframe always gets the
            // freshly-flushed schema, not whatever the dev server cached.
            setPreviewUrl(`${PREVIEW_BASE}/p/${projectId}${slug}?v=${Date.now()}`);
            setPreviewOpen(true);
            setPreviewing(false);
          }
        }}
        disabled={previewing}
        className={ICON_BTN}
        title={previewing ? "Saving…" : "Preview in production renderer"}
        aria-label="Preview"
      >
        {previewing ? <Loader2 size={16} className="animate-spin" /> : <Eye size={16} />}
      </button>

      <PreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        url={previewUrl}
        initialDevice={device}
      />

      <ExportPanel projectId={projectId} />

      <button
        onClick={() => setAiOpen(true)}
        className={ICON_BTN}
        title="AI edit (prompt the LLM)"
        aria-label="AI edit"
      >
        <Sparkles size={16} className="text-amber-500" />
      </button>

      <AiPromptModal
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        projectId={projectId}
      />

      <div className="flex items-center gap-1.5 text-xs mx-2">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            isDirty ? "bg-amber-500" : "bg-emerald-500"
          }`}
        />
        <span className="text-muted-foreground">{isDirty ? "Unsaved" : "Saved"}</span>
      </div>

      <button
        onClick={onSave}
        disabled={!isDirty}
        // BUG-009: the "Saved" indicator (left) already derives from isDirty, but
        // the Save button stayed full-emphasis black even when nothing was dirty —
        // reading as two conflicting states. Fade + disable it when already saved.
        className="h-7 px-3 rounded bg-foreground text-background text-xs font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:opacity-40"
      >
        {isDirty ? "Save" : "Saved"}
      </button>
    </header>
  );
}
