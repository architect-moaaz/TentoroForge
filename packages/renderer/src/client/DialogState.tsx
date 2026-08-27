"use client";
import * as React from "react";

/**
 * DialogStateContext — engine-level open/close state for schema Dialog nodes.
 *
 * Schemas reference dialogs by id (e.g. `<Dialog id="viewContact">`). Buttons
 * with an `opensDialog` prop render `data-dialog-open="<id>"` so the engine's
 * delegated click handler can call `openDialog(id)` here. The library's
 * Dialog component reads the open flag through useDialogState() to decide
 * whether to mount its Radix Dialog tree.
 *
 * Lives in @tentoroforge/renderer so the library (which imports renderer)
 * can reach it without forcing a library→engine dependency edge — engine
 * already depends on library, so the reverse direction would create a cycle.
 */
export type DialogState = {
  open: Record<string, boolean>;
  openDialog: (id: string) => void;
  closeDialog: (id: string) => void;
  toggleDialog: (id: string) => void;
};

export const DialogStateContext = React.createContext<DialogState | null>(null);

/** Returns the engine's dialog state, or null if rendered outside the
 *  DialogStateProvider (e.g. in standalone unit tests). */
export function useDialogState(): DialogState | null {
  return React.useContext(DialogStateContext);
}

export function DialogStateProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState<Record<string, boolean>>({});

  const openDialog = React.useCallback((id: string) => {
    setOpen((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
  }, []);
  const closeDialog = React.useCallback((id: string) => {
    setOpen((prev) => {
      if (!prev[id]) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);
  const toggleDialog = React.useCallback((id: string) => {
    setOpen((prev) => {
      const next = { ...prev };
      if (next[id]) delete next[id];
      else next[id] = true;
      return next;
    });
  }, []);

  const value = React.useMemo<DialogState>(
    () => ({ open, openDialog, closeDialog, toggleDialog }),
    [open, openDialog, closeDialog, toggleDialog],
  );

  return (
    <DialogStateContext.Provider value={value}>
      {children}
    </DialogStateContext.Provider>
  );
}
