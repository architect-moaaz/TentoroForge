import type { Mutation } from "../../state/types";

export function formatMutation(m: Mutation): string {
  switch (m.kind) {
    case "insert-node":
      return `insert-node → ${m.parentId}[${m.index}] (${m.node.type})`;
    case "remove-node":
      return `remove-node ← ${m.id}`;
    case "move-node":
      return `move-node ${m.id} → ${m.toParentId}[${m.toIndex}]`;
    case "set-prop":
      return `set-prop ${m.id}.${m.key}`;
    case "set-style":
      return `set-style ${m.id}.${m.key}`;
    case "set-bind":
      return `set-bind ${m.id}`;
    case "set-visible-if":
      return `set-visible-if ${m.id}`;
    case "set-event":
      return `set-event ${m.id}.${m.eventName}`;
    case "rename-node-id":
      return `rename ${m.oldId} → ${m.newId}`;
    case "composite":
      return `composite (${m.mutations.length} mutations)`;
    default: {
      // Exhaustive check — TypeScript will warn if a case is missing
      const _never: never = m;
      return `unknown mutation`;
    }
  }
}
