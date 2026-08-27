import type { SchemaNode } from "./types.js";

export type CodeConnectMapping = {
  libraryName: string;
  propsTransform: (props: Record<string, unknown>) => Record<string, unknown>;
};

export type CodeConnectMappings = Record<string, CodeConnectMapping>;

/**
 * Recursively walk a schema node tree, applying Code Connect mappings.
 * When a node's type matches a mapping key:
 *   - Rename node.type to mapping.libraryName
 *   - Replace node.props with the result of mapping.propsTransform(node.props)
 */
export function applyCodeConnect(
  node: SchemaNode,
  mappings: CodeConnectMappings
): SchemaNode {
  // Apply mapping to this node if found
  const mapping = mappings[node.type];
  let transformed: SchemaNode;

  if (mapping) {
    const newProps = mapping.propsTransform(
      (node.props ?? {}) as Record<string, unknown>
    ) as Record<string, unknown>;
    transformed = {
      ...node,
      type: mapping.libraryName,
      props: newProps,
    };
  } else {
    transformed = { ...node };
  }

  // Recursively apply to children
  if (transformed.children && transformed.children.length > 0) {
    transformed.children = transformed.children.map((child) =>
      applyCodeConnect(child, mappings)
    );
  }

  return transformed;
}
