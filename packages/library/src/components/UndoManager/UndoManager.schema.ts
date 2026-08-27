import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * UndoManager — Spec E Wave 1. Global toast bar that appears whenever
 * the runtime's mutation queue emits an "undoable" event. Renders
 * nothing when the queue is empty. Clicking Undo dispatches the
 * inverse mutation the queue captured at the time of the change.
 *
 * The queue itself lives in `@forge/renderer` (mutation-queue.ts +
 * undo-manager.ts); this component is a pure presentational shell.
 */
export const UndoManagerProps = z
  .object({
    /** Where on the viewport to dock the toast bar. */
    position: z
      .enum(["bottom-left", "bottom-center", "bottom-right", "top-center"])
      .default("bottom-center"),
    /** Auto-dismiss timeout in ms. 0 keeps it until dismissed manually. */
    timeoutMs: z.number().int().min(0).max(120_000).default(6000),
    /** Optional label prefix ("Item deleted" → "Item deleted. Undo?"). */
    labelPrefix: z.string().optional(),
    /** Maximum number of pending undo entries to stack. Older ones drop. */
    maxStack: z.number().int().min(1).max(20).default(5),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type UndoManagerPropsType = z.infer<typeof UndoManagerProps>;
