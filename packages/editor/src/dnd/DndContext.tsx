import { DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import type { ReactNode } from "react";
import type { EditorStoreApi } from "../state/store";
import type { Registry } from "@tentoroforge/library";
import { canDrop } from "./validate-drop";
import { buildInsertNode, buildMoveNode, findParentId, generateNodeId } from "../state/mutations";
import { defaultsFor } from "../panes/Palette/paletteDefaults";
import { selectCurrentPage } from "../state/selectors";
import type { Mutation } from "../state/types";

export function DndProvider({ store, registry, children }: { store: EditorStoreApi; registry: Registry; children: ReactNode }) {
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor));

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over) return;
    const activeData = active.data.current as { kind: "palette" | "node"; libraryName?: string; id?: string };
    const overId = over.id as string;
    const page = selectCurrentPage(store.getState())?.schema;

    let payload: any;
    if (activeData.kind === "palette") payload = { kind: "palette", libraryName: activeData.libraryName };
    else if (activeData.kind === "node") payload = { kind: "node", id: activeData.id };
    else return;

    if (!page || !canDrop(payload, overId, page, registry)) return;

    if (payload.kind === "palette") {
      // Seed v2-conformant default props (and starter children where the
      // schema needs them — Tabs needs children.length === tabs[].length,
      // Split needs exactly 2 children, etc.). Without these, dropping
      // a Button onto the canvas would create {props:{}} which fails
      // ButtonProps.label.min(1) and surfaces as "⚠ Button: invalid props".
      const seed = defaultsFor(payload.libraryName);
      const node: any = {
        id: generateNodeId(),
        type: payload.libraryName,
        ...(seed.props !== undefined ? { props: seed.props } : { props: {} }),
        ...(seed.children !== undefined ? { children: seed.children } : {}),
      };
      const m = buildInsertNode(overId, 0, node);
      store.getState().apply(m);
      store.getState().selectNode(node.id);
    } else if (payload.kind === "node") {
      const pageState = selectCurrentPage(store.getState())!;
      const selection = pageState.selection;

      // Bulk move: dragged node is in selection AND all selected share same parent
      const allSameParent =
        selection.includes(payload.id) &&
        selection.length > 1 &&
        selection.every(
          (id) => findParentId(page.root, id) === findParentId(page.root, selection[0])
        );

      if (allSameParent) {
        const subs: Mutation[] = selection.map((id) =>
          buildMoveNode(id, overId, 0, page)
        );
        store.getState().apply({ kind: "composite", mutations: subs });
      } else {
        store.getState().apply(buildMoveNode(payload.id, overId, 0, page));
      }
    }
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      {children}
    </DndContext>
  );
}
