"use client";
import { useContext, type ReactNode } from "react";
import * as RDialog from "@radix-ui/react-dialog";
import { DialogStateContext } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";

type Props = {
  /** Required — the Dialog is opened by a Button whose `opensDialog` prop
   *  matches this id. Same id is used by DialogStateContext to look up
   *  whether the dialog is currently open. */
  id: string;
  title?: string;
  description?: string;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  style?: StyleSlotT;
  children?: ReactNode;
};

const SIZE_TO_MAXW: Record<string, string> = {
  sm: "max-w-md",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

export function Dialog({
  id,
  title,
  description,
  size = "md",
  className,
  style,
  children,
}: Props) {
  const ctx = useContext(DialogStateContext);
  const open = ctx?.open?.[id] ?? false;
  const onOpenChange = (next: boolean) => {
    if (!ctx) return;
    if (next) ctx.openDialog(id);
    else ctx.closeDialog(id);
  };

  const maxW = SIZE_TO_MAXW[size] ?? SIZE_TO_MAXW.md;

  // ── Design-time fallback ────────────────────────────────────────────────
  // With no DialogStateProvider in scope (the editor canvas, or a standalone
  // render) `open` can never become true, so the Radix Portal rendered NOTHING:
  // the node measured 0×0 and any child dropped into it disappeared — work lost
  // invisibly. When there is no provider we render the dialog's content inline,
  // as a plain bordered container, so the node and its children are visible and
  // selectable. A generated app always mounts DialogStateProvider, so this
  // branch never runs there and runtime open/close behaviour is unchanged.
  if (!ctx) {
    const inlineClass = [
      "relative w-full",
      maxW,
      "bg-background rounded-lg border border-border shadow-sm",
      "p-6",
      className ?? "",
    ].filter(Boolean).join(" ");
    return (
      <div
        data-node-id={id}
        data-dialog-inline=""
        className={inlineClass}
        style={resolveStyle(style)}
      >
        {(title || description) && (
          <div className="space-y-1 mb-4">
            {title && (
              <div className="text-lg font-semibold leading-none">{title}</div>
            )}
            {description && (
              <div className="text-sm text-muted-foreground">{description}</div>
            )}
          </div>
        )}
        {children}
      </div>
    );
  }

  const contentClass = [
    "fixed start-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
    "w-full mx-4",
    maxW,
    "bg-background rounded-lg shadow-xl",
    "p-6 max-h-[90vh] overflow-y-auto",
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40" />
        <RDialog.Content
          data-node-id={id}
          className={`${contentClass} z-50`}
          style={resolveStyle(style)}
        >
          {(title || description) && (
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="space-y-1">
                {title && (
                  <RDialog.Title className="text-lg font-semibold leading-none">
                    {title}
                  </RDialog.Title>
                )}
                {description && (
                  <RDialog.Description className="text-sm text-muted-foreground">
                    {description}
                  </RDialog.Description>
                )}
              </div>
              <RDialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  ×
                </button>
              </RDialog.Close>
            </div>
          )}
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}
