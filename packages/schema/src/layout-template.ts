import { z } from "zod";
import { Node } from "./nodes";

function hasSlot(node: unknown): boolean {
  if (!node || typeof node !== "object") return false;
  const n = node as Record<string, unknown>;
  if (n["type"] === "Slot") return true;
  if (Array.isArray(n["children"])) return (n["children"] as unknown[]).some(hasSlot);
  return false;
}

export const LayoutTemplate = z
  .object({
    schemaVersion: z.literal("1"),
    id: z.string().min(1),
    root: Node,
  })
  .strict()
  .refine((tpl) => hasSlot(tpl.root), {
    message: "LayoutTemplate must contain at least one Slot in its tree",
  });

export type LayoutTemplate = z.infer<typeof LayoutTemplate>;
