"use client";
import { useEditorStore } from "@/lib/editor-store";
import { useEffect } from "react";

export function ErrorBanner() {
  const error = useEditorStore(s => s.lastError);
  const clear = useEditorStore(s => s.clearError);
  const saveError = useEditorStore(s => s.saveError);
  const clearSaveError = useEditorStore(s => s.setSaveError);

  // Transient edit-rejected errors auto-clear; save failures do NOT (the user
  // must know their work isn't persisted until a save succeeds or they dismiss).
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(clear, 5000);
    return () => clearTimeout(t);
  }, [error, clear]);

  if (!error && !saveError) return null;
  return (
    <div className="fixed top-3 right-3 z-50 flex max-w-md flex-col gap-2" role="alert">
      {saveError && (
        <div className="bg-destructive text-destructive-foreground rounded-md p-3 shadow-lg">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide mb-1">Couldn&apos;t save</p>
              <pre className="text-xs whitespace-pre-wrap font-mono">{saveError}</pre>
            </div>
            <button onClick={() => clearSaveError(null)} className="text-lg leading-none" aria-label="dismiss save error">×</button>
          </div>
        </div>
      )}
      {error && (
        <div className="bg-destructive text-destructive-foreground rounded-md p-3 shadow-lg">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide mb-1">Edit rejected</p>
              <pre className="text-xs whitespace-pre-wrap font-mono">{error}</pre>
            </div>
            <button onClick={clear} className="text-lg leading-none" aria-label="dismiss">×</button>
          </div>
        </div>
      )}
    </div>
  );
}
