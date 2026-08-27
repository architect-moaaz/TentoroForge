import type { Page, Nodes } from "@tentoroforge/schema";

type RenderedNode = {
  type: string;
  id: string;
  props?: Record<string, unknown>;
  children?: RenderedNode[];
};

export function renderToObject(page: Page): RenderedNode {
  return walk(page.root as Nodes.Node);
}

function walk(node: any): RenderedNode {
  return {
    type: node.type,
    id: node.id,
    props: node.props,
    children: Array.isArray(node.children) ? node.children.map(walk) : undefined,
  };
}
