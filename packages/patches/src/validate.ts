import type { Artifacts, SchemaNode } from "./types";

const HEX_RE = /#[0-9A-Fa-f]{3,8}\b/;
const PX_RE = /\b\d+\s*px\b/;

function* walk(node: SchemaNode): Iterable<SchemaNode> {
  yield node;
  for (const c of node.children ?? []) yield* walk(c);
  if (node.slots) {
    for (const arr of Object.values(node.slots)) {
      for (const c of arr) yield* walk(c);
    }
  }
}

export function validateIdUniqueness(a: Artifacts): string[] {
  const errs: string[] = [];
  const seen = new Set<string>();
  for (const [pid, page] of Object.entries(a.pageSchemas ?? {})) {
    if (!page.root) { errs.push(`${pid}: missing root`); continue; }
    for (const n of walk(page.root)) {
      if (!n.id) { errs.push(`${pid}/<unknown>: missing id on ${n.type}`); continue; }
      if (seen.has(n.id)) errs.push(`duplicate node id: ${n.id}`);
      seen.add(n.id);
    }
  }
  return errs;
}

export type RegistryLike = Record<string, { props: Record<string, unknown> }>;

/**
 * Renderer built-in node types — handled directly by dispatch.tsx, not via
 * the library registry. Must be allowed by every registry-closure check or
 * schemas that use any primitive (Text, Image, Stack, Row, …) get rejected
 * at commit time even though the renderer can render them perfectly well.
 *
 * Keep in sync with the switch in `packages/renderer/src/runtime/dispatch.tsx`.
 */
const RENDERER_BUILTINS: ReadonlySet<string> = new Set([
  // Data / flow
  "Repeat", "Conditional", "DataBoundary",
  // Layout
  "Stack", "Row", "Grid", "Container", "Spacer", "Box",
  // Primitives
  "Text", "Image", "Icon",
  // Composition
  "Slot", "PageOutlet",
  // Escape hatch
  "Custom",
]);

/**
 * Strict registry check — only flags issues that would actually break
 * rendering: unknown component types and missing-type. Unknown prop
 * names pass silently because library components accept many props
 * the simplified @forge/registry doesn't list.
 *
 * Used by the editor commit-boundary check — we don't want to reject
 * every edit just because the registry hasn't been expanded yet.
 */
export function validateRegistryTypes(a: Artifacts, registry: RegistryLike): string[] {
  const errs: string[] = [];
  for (const [pid, page] of Object.entries(a.pageSchemas ?? {})) {
    if (!page.root) continue;
    for (const n of walk(page.root)) {
      if (!n.type) { errs.push(`${pid}/${n.id ?? "?"}: missing type`); continue; }
      if (RENDERER_BUILTINS.has(n.type)) continue;
      if (!registry[n.type]) {
        errs.push(`${pid}/${n.id ?? "?"}: unknown component '${n.type}'`);
      }
    }
  }
  return errs;
}

/**
 * Full closure check — unknown components AND unknown props.
 * Used by the LLM peer patcher at generation time where we want strict
 * conformance because the registry digest is the prompt's component
 * vocabulary.
 */
export function validateRegistryClosure(a: Artifacts, registry: RegistryLike): string[] {
  const errs: string[] = [];
  for (const [pid, page] of Object.entries(a.pageSchemas ?? {})) {
    if (!page.root) continue;
    for (const n of walk(page.root)) {
      if (!n.type) { errs.push(`${pid}/${n.id ?? "?"}: missing type`); continue; }
      if (RENDERER_BUILTINS.has(n.type)) continue;
      const entry = registry[n.type];
      if (!entry) { errs.push(`${pid}/${n.id ?? "?"}: unknown component '${n.type}'`); continue; }
      const entryProps = entry.props ?? {};
      for (const propName of Object.keys(n.props ?? {})) {
        if (!(propName in entryProps)) {
          errs.push(`${pid}/${n.id ?? "?"}.${propName}: unknown prop on '${n.type}'`);
        }
      }
    }
  }
  return errs;
}

export function validateTokenClosure(a: Artifacts): string[] {
  const errs: string[] = [];
  for (const [pid, page] of Object.entries(a.pageSchemas ?? {})) {
    if (!page.root) continue;
    for (const n of walk(page.root)) {
      for (const [name, val] of Object.entries(n.props ?? {})) {
        const s = typeof val === "string" ? val : "";
        if (HEX_RE.test(s)) errs.push(`${pid}/${n.id ?? "?"}.${name}: raw hex '${val}'`);
        if (PX_RE.test(s))  errs.push(`${pid}/${n.id ?? "?"}.${name}: raw px '${val}'`);
      }
    }
  }
  return errs;
}

export function validateNavConsistency(a: Artifacts): string[] {
  const errs: string[] = [];
  const pageIds = new Set(Object.keys(a.pageSchemas ?? {}));
  const navIds = new Set((a.navFlow?.pages ?? []).map(p => (p as any).id));
  for (const id of pageIds) if (!navIds.has(id)) errs.push(`pageSchemas['${id}'] has no navFlow entry`);
  for (const id of navIds) if (!pageIds.has(id)) errs.push(`navFlow.pages['${id}'] has no pageSchemas entry`);
  for (const t of (a.navFlow?.transitions ?? [])) {
    const tt: any = t;
    if (tt.from && !navIds.has(tt.from)) errs.push(`transition ${tt.id}: from='${tt.from}' unknown`);
    if (tt.to && !navIds.has(tt.to)) errs.push(`transition ${tt.id}: to='${tt.to}' unknown`);
  }
  const ip = a.navFlow?.initialPage;
  if (ip && !navIds.has(ip)) errs.push(`navFlow.initialPage='${ip}' unknown`);
  return errs;
}

/**
 * Subset that's safe to run at the editor commit boundary. Skips
 * prop-level closure (too noisy for live editing) and token closure
 * (cosmetic, not breaking). Use validateAll for the LLM peer-patcher's
 * generation-time check.
 */
export function validateForCommit(a: Artifacts, registry?: RegistryLike): string[] {
  return [
    ...validateIdUniqueness(a),
    ...(registry ? validateRegistryTypes(a, registry) : []),
  ];
}

export function validateAll(a: Artifacts, registry?: RegistryLike): string[] {
  return [
    ...validateIdUniqueness(a),
    ...(registry ? validateRegistryClosure(a, registry) : []),
    ...validateTokenClosure(a),
    ...validateNavConsistency(a),
  ];
}
