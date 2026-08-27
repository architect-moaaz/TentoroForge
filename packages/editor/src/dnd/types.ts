import type { NodeId } from "../state/types";

export type DragPayload =
  | { kind: "palette"; libraryName: string }
  | { kind: "node"; id: NodeId };

export type PaletteItem = {
  libraryName: string;
  category: string;
  acceptsChildren: boolean;
};
