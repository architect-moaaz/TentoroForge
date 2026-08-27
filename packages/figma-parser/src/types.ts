export type SchemaNode = {
  id: string;
  type: string;
  props?: Record<string, unknown>;
  style?: Record<string, string>;
  children?: SchemaNode[];
};

export type ParsedResult = {
  schema: { root: SchemaNode };
  unmappedNodes: { id: string; reason: string; jsx: string }[];
};
