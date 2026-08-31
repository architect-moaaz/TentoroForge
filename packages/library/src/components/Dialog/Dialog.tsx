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
  // No engine wrapper supplied (e.g. component rendered standalone in tests)
  // → render closed; tests can supply a stub context.
  const open = ctx?.open?.[id] ?? false;
  const onOpenChange = (next: boolean) => {
    if (!ctx) return;
    if (next) ctx.openDialog(id);
    else ctx.closeDialog(id);
  };

  const maxW = SIZE_TO_MAXW[size] ?? SIZE_TO_MAXW.md;
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
