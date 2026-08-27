"use client";
import { useState, useContext } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { WorkflowDispatcherContext } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Props = {
  triggerLabel: string;
  title: string;
  description: string;
  workflow: string;
  args?: Record<string, unknown>;
  confirmLabel?: string;
  cancelLabel?: string;
  style?: StyleSlotT;
  /** Test injection — bypasses context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

export function ConfirmDialog({
  triggerLabel,
  title,
  description,
  workflow,
  args,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  style,
  __dispatch,
}: Props) {
  const [open, setOpen] = useState(false);
  const ctxDispatch = useContext(WorkflowDispatcherContext);

  function handleConfirm() {
    const dispatch = __dispatch ?? ctxDispatch;
    if (dispatch) dispatch(workflow, args);
    setOpen(false);
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" style={resolveStyle(style)} {...useMotion(style?.motion)}>{triggerLabel}</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0,0,0,0.4)",
          }}
        />
        <Dialog.Content
          style={{
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            background: "#fff",
            borderRadius: "0.5rem",
            padding: "1.5rem",
            minWidth: "20rem",
            boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
          }}
        >
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description style={{ margin: "0.75rem 0 1.25rem" }}>
            {description}
          </Dialog.Description>
          <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
            <Dialog.Close asChild>
              <button type="button">{cancelLabel}</button>
            </Dialog.Close>
            <button type="button" onClick={handleConfirm}>
              {confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
