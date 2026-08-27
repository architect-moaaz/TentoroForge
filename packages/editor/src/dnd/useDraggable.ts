import { useDraggable as useDndKitDraggable } from "@dnd-kit/core";

export function useDraggable(args: { id: string; data: any }) {
  return useDndKitDraggable({ id: args.id, data: args.data });
}
