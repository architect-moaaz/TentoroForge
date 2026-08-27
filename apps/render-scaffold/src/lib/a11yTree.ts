// apps/render-scaffold/src/lib/a11yTree.ts
// Walks a JSON schema's root and produces a text-only outline.
// Used by the render service to feed structural context to the vision evaluator.
type Node = { id?: string; type?: string; props?: Record<string, unknown>; children?: Node[] };

export function buildA11yTree(schema: { root: Node; meta?: { title?: string } }): string {
  const lines: string[] = [];
  if (schema.meta?.title) lines.push(`# ${schema.meta.title}`);
  function walk(n: Node, depth: number): void {
    if (!n || typeof n !== "object") return;
    const indent = "  ".repeat(depth);
    const label = textOf(n);
    lines.push(`${indent}- ${n.type ?? "?"}${label ? ` "${label}"` : ""}`);
    for (const c of n.children ?? []) walk(c, depth + 1);
  }
  walk(schema.root, 0);
  return lines.join("\n");
}

function textOf(n: Node): string {
  const p = n.props ?? {};
  for (const k of ["headline", "title", "label", "content", "value", "name"]) {
    const v = (p as any)[k];
    if (typeof v === "string" && v.length > 0 && v.length < 80) return v;
  }
  return "";
}
