import type { Page, LayoutTemplate } from "@tentoroforge/schema";

// Walk the layout's root tree, replacing Slot nodes with the page root or
// any matching value from page.slots. Returns a new node tree.
export function applyLayout(page: Page, template: LayoutTemplate): any {
  function walk(node: any): any {
    if (node.type === "Slot") {
      const name = node.props.name;
      if (name === "main") return page.root;
      const fill = (page as any).slots?.[name];
      if (!fill) throw new Error(`layout slot '${name}' has no fill on page '${page.id}'`);
      return fill;
    }
    if (Array.isArray(node.children)) {
      return { ...node, children: node.children.map(walk) };
    }
    return node;
  }
  return walk(template.root);
}
