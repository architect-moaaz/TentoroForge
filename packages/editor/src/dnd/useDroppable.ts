import { useDroppable as useDndKitDroppable } from "@dnd-kit/core";

export function useDroppable(args: { id: string }) {
  return useDndKitDroppable({ id: args.id });
}
