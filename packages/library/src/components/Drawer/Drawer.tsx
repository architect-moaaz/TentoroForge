"use client";
import * as React from "react";
import * as RDialog from "@radix-ui/react-dialog";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { DrawerPropsType } from "./Drawer.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { cx } from "../../util/cx";
import { useMotion } from "../../style/useMotion";
import { useDesignTime } from "@tentoroforge/renderer";

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

export function Drawer({ trigger, title, description, side = "right", content, style, className, children }: DrawerProps) {
  // `className` was declared in this component's Zod schema AND its node schema
  // and destructured by neither, so a producer writing `props.className` on the
  // node had it silently dropped. Merged last so an authored utility class wins
  // over the built-in one, which is the reason a producer sets it. See util/cx.

  // OPENING A DRAWER ON THE CANVAS MODAL-BLOCKED THE WHOLE EDITOR.
  //
  // Radix portals the dialog to `document.body`, so the scrim measured the
  // BROWSER VIEWPORT (1525x678) rather than the canvas frame, and modal mode
  // puts `pointer-events: none` on the body: the component palette, the pages
  // rail and the Properties panel were all behind a modal layer belonging to a
  // node being edited. `elementFromPoint` over the palette returned the scrim.
  // The way out was Escape, which the author had to guess.
  //
  // `modal={false}` removes exactly the two things that cause it — the scrim and
  // the body pointer-events lock — and keeps everything the author is trying to
  // look at: the panel, its side, its title, description and content. In a
  // running app the drawer stays fully modal, which is what a drawer is.
  const modal = !useDesignTime();

  return (
    <RDialog.Root modal={modal}>
      <RDialog.Trigger asChild>
        <button type="button" data-drawer="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className={cx("inline-flex items-center rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
          {trigger}
        </button>
      </RDialog.Trigger>
      <RDialog.Portal>
        {modal && <RDialog.Overlay className="fixed inset-0 z-40 bg-black/40" />}
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
