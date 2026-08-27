// The canonical metadata shape for every component in Tentoro Forge.

export type ControlType =
  | "text" | "textarea" | "number" | "select" | "toggle"
  | "color" | "spacing" | "binding" | "actionPicker" | "iconPicker";

export interface PropDescriptor {
  type: "string" | "number" | "boolean" | "enum" | "action" | "binding";
  default?: unknown;
  options?: readonly string[];          // for enum
  control: ControlType;
  group: "content" | "style" | "state" | "behavior" | "data";
  description?: string;
}

export type SlotRule =
  | { type: "leaf" }
  | { type: "single"; accepts?: readonly string[] }
  | { type: "list"; accepts?: readonly string[]; rejects?: readonly string[]; maxChildren?: number };

export interface RegistryEntry {
  name: string;
  category: "layout" | "input" | "display" | "navigation" | "feedback" | "data";
  icon?: string;
  description?: string;
  slots: SlotRule;
  props: Record<string, PropDescriptor>;
}

export type Registry = Record<string, RegistryEntry>;
