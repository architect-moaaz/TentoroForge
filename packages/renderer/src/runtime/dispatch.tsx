import { cloneElement, isValidElement, type ReactNode } from "react";
import { CustomHtml } from "../nodes/library/CustomHtml";
import { Stack, Row, Grid, GridCell, Container, Spacer } from "../nodes/layout";
import { Box, Text, Image } from "../nodes/primitive";
import { Repeat, Conditional, DataBoundary } from "../nodes/data";
import { Slot } from "../nodes/slot/Slot";
import { PageOutlet } from "../nodes/shell/PageOutlet";
import { LibraryDispatcher } from "../nodes/library/LibraryDispatcher";
import { NodeErrorBoundary } from "../nodes/library/NodeErrorBoundary";
import { evalExpression } from "./bindings";
import { interpolateDeep } from "./interpolate";
import { applyStyleSlot } from "./style-slot";
import { syntheticNodeId } from "@forge/patches";

/** Minimal structural interface for a registry — matches Library.Registry without the import. */
type RegistryLike = {
  has(name: string): boolean;
  get(name: string): { component: unknown; propsSchema: unknown } | undefined;
  validateProps(name: string, props: unknown): Record<string, unknown>;
};

export type DispatchContext = {
  data: Record<string, unknown>;
  user?: Record<string, unknown>;
  slots?: Record<string, any>;
  layouts?: Record<string, any>;
  /** Component registry for library node dispatch. */
  registry?: RegistryLike;
  /**
   * Optional override for Custom-node rendering. When set, this callback is
   * invoked instead of the default dangerouslySetInnerHTML dispatch for every
   * node whose type is "Custom". This hook exists so the editor (Task 33) can
   * mount <CustomNodePreview> — which adds a floating edit chip and disables
   * pointer-events on the inner HTML — without forking the dispatch switch.
   *
   * Callers that don't set this field get the default sanitised-HTML render,
   * so this is a fully backward-compatible addition to the public API.
   */
  customRenderer?: (node: any, ctx: DispatchContext) => ReactNode;
};


/** Input nodes that support `props.optionsFrom` dataSource-driven options. */
const OPTION_SOURCE_TYPES = new Set(["Select", "Combobox", "MultiSelect"]);

/**
 * Expand a node's `props.optionsFrom` into a concrete `props.options` array by
 * reading the named dataSource out of `data`. Returns a new node with the
 * resolved options and `optionsFrom` removed. When the source is absent or
 * yields no usable rows, returns the node with only `optionsFrom` stripped so
 * its static fallback options remain (and validateProps never sees the helper
 * field, which not every consumer's prop schema knows about).
 */
function expandOptionsFrom(node: any, data: Record<string, unknown>): any {
  const props = node.props as Record<string, unknown>;
  const of = props.optionsFrom as
    | { source?: unknown; value?: unknown; label?: unknown }
    | undefined;
  if (!of || typeof of.source !== "string") return node;

  const { optionsFrom: _omit, ...rest } = props;
  const rows = data?.[of.source];
  if (!Array.isArray(rows) || rows.length === 0) {
    return { ...node, props: rest }; // keep static fallback options
  }
  const valueKey = typeof of.value === "string" && of.value ? of.value : "id";
  const labelKey = typeof of.label === "string" && of.label ? of.label : "name";
  const options: Array<{ value: string; label: string }> = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const raw = (row as Record<string, unknown>)[valueKey];
    if (raw === undefined || raw === null || raw === "") continue;
    const value = String(raw);
    const labelRaw = (row as Record<string, unknown>)[labelKey];
    const label =
      labelRaw === undefined || labelRaw === null || labelRaw === ""
        ? value
        : String(labelRaw);
    options.push({ value, label });
  }
  // No usable rows (e.g. every item lacked the value field) → keep the fallback.
  if (options.length === 0) return { ...node, props: rest };
  return { ...node, props: { ...rest, options } };
}

/**
 * Props that a library component renders in REACT CHILD POSITION rather than
 * consuming as data — AppShell's four composition slots are the whole set
 * today. `packages/schema/src/nodes/enterprise.ts` types each of them as a
 * NodeV2Ref (a schema sub-tree) and the registry description says the same,
 * but nothing ever converted that sub-tree into rendered nodes: AppShell.tsx
 * does `{sidebar}` verbatim.
 *
 * Two consequences, both fatal before this map existed:
 *   • the documented feature (compose a sidebar/topbar sub-tree) rendered
 *     nothing correct — React threw on the plain object;
 *   • validateProps cannot coerce these back to safety. Its step-3 rules
 *     rescue "non-array where an array is expected"; a NodeV2 union mismatch
 *     produces an invalid_union error it has no rule for, so the object
 *     survives verbatim into the child position, throws "Objects are not valid
 *     as a React child", and — because Fizz has no error boundaries — takes
 *     the whole SSR document with it (docs/editor-audit/containment.md #1).
 *
 * The conversion happens here, in dispatch, because this is the only layer
 * that has both the value and a renderer for it; the library must stay
 * dispatch-unaware.
 */
const NODE_SLOT_PROPS: Record<string, readonly string[]> = {
  AppShell: ["sidebar", "topbar", "actions", "rightRail"],
};

/** True for a value React can legally put in child position on its own. */
function isRenderablePrimitive(v: unknown): boolean {
  return (
    v === null ||
    v === undefined ||
    typeof v === "string" ||
    typeof v === "number" ||
    typeof v === "boolean"
  );
}

/**
 * Convert the node-slot props of `type` into rendered ReactNodes.
 *
 * A schema sub-tree is rendered through renderNode (delivering the documented
 * feature). Strings/numbers pass through as text. Anything else — an action
 * object from the Properties panel, a stray array of scalars, a bound value
 * that never resolved — becomes a labelled inline placeholder, because
 * rendering it would be the crash this function exists to prevent, and
 * silently dropping it would leave the user with an empty rail and no clue
 * why.
 */
function resolveNodeSlotProps(
  type: string,
  props: Record<string, unknown>,
  ctx: DispatchContext,
): Record<string, unknown> {
  const slotNames = NODE_SLOT_PROPS[type];
  if (!slotNames) return props;
  let out: Record<string, unknown> | null = null;
  for (const name of slotNames) {
    const v = props[name];
    if (v === undefined || isRenderablePrimitive(v)) continue;
    const resolved = Array.isArray(v)
      ? v.map((c, i) => {
          // Same keying rule as the children pass below: a schema node id when
          // there is one, else the index — otherwise React warns for every
          // multi-node slot.
          const el = renderSlotValue(c, `${type}.${name}[${i}]`, ctx);
          const key = (c as any)?.id ?? i;
          return isValidElement(el) ? cloneElement(el, { key }) : el;
        })
      : renderSlotValue(v, `${type}.${name}`, ctx);
    out ??= { ...props };
    out[name] = resolved;
  }
  return out ?? props;
}

function renderSlotValue(v: unknown, label: string, ctx: DispatchContext): ReactNode {
  if (isRenderablePrimitive(v)) return v as ReactNode;
  if (isValidElement(v)) return v;
  if (v && typeof v === "object" && typeof (v as any).type === "string") {
    return renderNode(v, ctx);
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 8px",
        border: "1px dashed hsl(var(--destructive, 0 70% 50%))",
        borderRadius: 4,
        background: "hsl(var(--destructive, 0 70% 50%) / 0.08)",
        color: "hsl(var(--destructive, 0 70% 50%))",
        fontSize: 12,
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
      }}
      data-invalid-node={label}
      title={`${label} is not a schema node or text`}
    >
      ⚠ {label}: not renderable
    </span>
  );
}

export function renderNode(node: any, ctx: DispatchContext): ReactNode {
  // Ensure every node has a stable id so the editor overlay can locate it
  // via [data-node-id]. Schemas from the legacy pipeline may omit the id field.
  if (!node.id) {
    node = { ...node, id: syntheticNodeId(node) };
  }

  // Evaluate visibleIf before rendering anything; treat expression errors as false.
  if (node.visibleIf) {
    const v = evalExpression(node.visibleIf, { ...ctx.data, user: ctx.user });
    if (!v) return null;
  }

  // Interpolate Mustache-style {{expr}} placeholders in the node's props
  // against ctx.data BEFORE dispatch. This is what makes content like
  // "Welcome, {{user.name}}!" or {{leaveRequest.id}} resolve at render time
  // — the LLM-generated schemas write these literals everywhere instead of
  // using the formal `bind` field. Children stay un-walked here; each child's
  // own renderNode call will run its own interpolation pass.
  if (node.props && typeof node.props === "object") {
    const interp = interpolateDeep(node.props, { ...ctx.data, user: ctx.user });
    node = { ...node, props: interp };
  }

  // Dynamic option expansion — Select/Combobox/MultiSelect may declare
  // `props.optionsFrom = { source, value, label }` to build their option list
  // from a page dataSource (a relational FK dropdown) instead of a static array.
  // Resolve it here, where ctx.data holds the loaded dataSource arrays, so the
  // library components stay data-unaware. `optionsFrom` is stripped afterwards so
  // it never reaches validateProps; the node's static `options` survive untouched
  // as the fallback when the source is missing/empty (preserving the min(1)
  // contract and an editor-preview placeholder).
  if (node.props && OPTION_SOURCE_TYPES.has(node.type)) {
    node = expandOptionsFrom(node, ctx.data);
  }

  // Data nodes manage their own child rendering (Repeat builds per-item scopes,
  // Conditional branches, DataBoundary wraps in try/catch). Pre-computing children
  // here would bypass their error-handling and scoping logic.
  switch (node.type) {
    case "Repeat":
      return <Repeat node={node} ctx={ctx} />;
    case "Conditional":
      return <Conditional node={node} ctx={ctx} />;
    case "DataBoundary":
      return <DataBoundary node={node} ctx={ctx} />;
    default:
      // P1-O13: dev-mode misuse warning. `bind` is only honored by iterator
      // nodes above; a `bind` on Grid/Stack/Card silently renders 0 items and
      // no error. This dropped nni3wjf6's /scans/[id]/prices page into 1 empty
      // card with no clue why. Warn once per (type,bind) pair in dev.
      if (
        (node as any).bind &&
        typeof (process as any) !== "undefined" &&
        (process as any).env?.NODE_ENV !== "production"
      ) {
        const key = `${node.type}:${(node as any).bind}`;
        const seen = ((globalThis as any).__forgeBindWarn ||= new Set<string>());
        if (!seen.has(key)) {
          seen.add(key);
          // eslint-disable-next-line no-console
          console.warn(
            `[renderer] node.bind="${(node as any).bind}" set on <${node.type}> ` +
            `— bind is only honored by iterator nodes (Repeat, List). ` +
            `Wrap children in a Repeat instead, or move the binding to a Repeat parent.`,
          );
        }
      }
      break;
  }

  // Pre-compute children for structural/primitive nodes. Each child gets a
  // stable React key derived from the schema node's id (falls back to index)
  // so list-rendering doesn't trigger React's missing-key warning.
  const children = (node.children ?? []).map((c: any, i: number) => {
    const rendered = renderNode(c, ctx);
    const key = c?.id ?? i;
    return isValidElement(rendered) ? cloneElement(rendered, { key }) : rendered;
  });
  switch (node.type) {
    case "Stack":
      return <Stack node={node} children={children} />;
    case "Row":
      return <Row node={node} children={children} />;
    case "Grid":
      return <Grid node={node} children={children} />;
    case "GridCell":
      return <GridCell node={node} children={children} />;
    case "Container":
      return <Container node={node} children={children} />;
    case "Spacer":
      return <Spacer node={node} />;
    case "Box":
      return <Box node={node} children={children} />;
    case "Text":
      return <Text node={node} ctx={ctx} />;
    case "Image":
      return <Image node={node} />;
    case "Icon": {
      // Deterministic Figma mapper emits Icon nodes that may carry a `src`
      // (when the asset-export pipeline has resolved a Lucide / SVG export)
      // or be empty (vector-only icon without a downloaded asset). The
      // Image renderer returns null for empty src, so empty Icon nodes
      // render nothing rather than the "⚠ Icon" unknown-type placeholder.
      //
      // Constrain default size: SVGs exported from Figma carry their natural
      // dimensions (often 1000+px). Without a w-/h-/size- utility on the
      // node's className the browser renders them at full size and they
      // dominate the layout. Inject a default w-5 h-5 (20px) when the schema
      // hasn't set its own sizing.
      const iconProps = node.props ?? {};
      const cn = typeof iconProps.className === "string" ? iconProps.className : "";
      const hasSizing = /\b(w-|h-|size-)/.test(cn);
      const sizedNode = hasSizing
        ? node
        : { ...node, props: { ...iconProps, className: `w-5 h-5 ${cn}`.trim() } };
      return <Image node={sizedNode} />;
    }
    case "Slot":
      return <Slot node={node} />;
    case "PageOutlet":
      // Shell composition: render the page content injected via PageOutletContext.
      // Works as a "use client" component because PageOutletContext.useContext
      // requires the React client runtime.
      return <PageOutlet />;
    case "Custom": {
      // If the caller supplied a customRenderer (e.g. the editor in Task 33),
      // delegate entirely so the editor can mount its own wrapper component
      // (CustomNodePreview with edit chip + pointer-events guard).
      if (ctx.customRenderer) return ctx.customRenderer(node, ctx);

      // Escape-hatch: render sanitized HTML. CustomHtml sanitizes on the CLIENT
      // with browser DOMPurify (lazily imported), so the renderer never pulls the
      // jsdom-backed isomorphic-dompurify onto the server — which would drag its
      // ESM-only encoding sub-deps into every page's server bundle and crash a
      // CJS require. Full XSS protection still applies once hydrated.
      const p = node.props ?? {};
      const rawHtml: string = typeof p.html === "string" ? p.html : "";
      const slotProps = applyStyleSlot(node.style);
      const className = ["custom-block", typeof p.tailwind === "string" ? p.tailwind : ""]
        .filter(Boolean)
        .join(" ");
      return (
        <CustomHtml
          html={rawHtml}
          nodeId={node.id}
          className={className || undefined}
          label={typeof p.label === "string" ? p.label : undefined}
          style={slotProps.style}
          dataMotion={slotProps["data-motion"] as string | undefined}
        />
      );
    }
    default:
      // Fall-through: check if registry has this type; if so, dispatch via LibraryDispatcher.
      // Validate props eagerly so errors surface here rather than deep inside the
      // component. If validation fails (e.g. LLM-generated schemas missing a
      // required prop) we render a labeled placeholder instead of throwing,
      // so the editor canvas stays usable while the user fixes the schema.
      if (ctx.registry && ctx.registry.has(node.type)) {
        try {
          const validatedProps = resolveNodeSlotProps(
            node.type,
            ctx.registry.validateProps(node.type, node.props ?? {}),
            ctx,
          );
          // Pass node.style through so library components (Task 20 StyleSlot mixin) can apply it.
          const propsWithStyle = node.style !== undefined
            ? { ...validatedProps, style: node.style }
            : validatedProps;
          return (
            <NodeErrorBoundary
              nodeType={node.type}
              // The id makes the error placeholder selectable on the canvas
              // (the editor hit-tests [data-node-id]); the props let it name
              // the prop that threw. Both are already validated here.
              nodeId={node.id}
              nodeProps={propsWithStyle as Record<string, unknown>}
            >
              <LibraryDispatcher
                node={node}
                ctx={ctx}
                validatedProps={propsWithStyle}
              >
                {children.length > 0 ? children : undefined}
              </LibraryDispatcher>
            </NodeErrorBoundary>
          );
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          return (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 8px",
                margin: "2px",
                border: "1px dashed hsl(var(--destructive, 0 70% 50%))",
                borderRadius: 4,
                background: "hsl(var(--destructive, 0 70% 50%) / 0.08)",
                color: "hsl(var(--destructive, 0 70% 50%))",
                fontSize: 12,
                fontFamily: "ui-sans-serif, system-ui, sans-serif",
              }}
              data-node-id={node.id}
              data-invalid-node={node.type}
              title={message}
            >
              ⚠ {node.type}: invalid props
            </span>
          );
        }
      }
      // Unknown node type: render an inline placeholder instead of crashing
      // the whole canvas. This keeps the editor usable when LLM-generated
      // schemas reference component names that aren't registered (yet).
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 8px",
            margin: "2px",
            border: "1px dashed hsl(var(--border, 0 0% 80%))",
            borderRadius: 4,
            background: "hsl(var(--muted, 0 0% 96%))",
            color: "hsl(var(--muted-foreground, 0 0% 45%))",
            fontSize: 12,
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
          }}
          data-node-id={node.id}
          data-unknown-node={node.type}
          title={`Component "${node.type}" is not registered`}
        >
          ⚠ {node.type}
        </span>
      );
  }
}
