"use client";
import * as React from "react";
import * as RDialog from "@radix-ui/react-dialog";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { DrawerPropsType } from "./Drawer.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface DrawerProps extends DrawerPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

const SIDE_CLASS: Record<string, string> = {
  left:   "inset-y-0 start-0 h-full w-80 border-e",
  right:  "inset-y-0 end-0 h-full w-80 border-s",
  top:    "inset-x-0 top-0 w-full border-b",
  bottom: "inset-x-0 bottom-0 w-full border-t",
};

export function Drawer({ trigger, title, description, side = "right", content, style, children }: DrawerProps) {
  return (
    <RDialog.Root>
      <RDialog.Trigger asChild>
        <button type="button" data-drawer="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className="inline-flex items-center rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {trigger}
        </button>
      </RDialog.Trigger>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <RDialog.Content data-side={side}
          className={`fixed z-50 bg-white p-4 shadow-lg border-input ${SIDE_CLASS[side]}`}>
          {title && <RDialog.Title className="text-base font-semibold text-foreground">{title}</RDialog.Title>}
          {description && <RDialog.Description className="text-sm text-muted-foreground">{description}</RDialog.Description>}
          <div className="mt-2 text-sm text-foreground">{children ?? content}</div>
          <RDialog.Close asChild>
            <button type="button" aria-label="Close" className="absolute end-3 top-3 text-muted-foreground hover:text-foreground">✕</button>
          </RDialog.Close>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}
