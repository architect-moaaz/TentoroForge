"use client";
import * as React from "react";
import { ChevronDown } from "lucide-react";
import { isColorTokenRef } from "@tentoroforge/renderer";
import { defaultTokens } from "@tentoroforge/library";
import type { EditorAction } from "@forge/patches";
import { useEditorStore } from "@/lib/editor-store";

const sectionLabelCls =
  "block px-3 py-2 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase";

// Token-style dropdown — visually matches the reference's chrome
function DropdownField({
  value,
  onChange,
  options,
  placeholder,
}: {
  value?: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
}) {
  return (
    <div className="relative mx-3 mb-2">
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-background border rounded-md pl-3 pr-8 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30"
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
      />
    </div>
  );
}

// Freeform size input (Width/Height/Min/Max). Values are RAW CSS strings
// ("240px", "50%", "auto", "32rem") written to node.style — the renderer emits
// them verbatim. Commits on blur / Enter (not per-keystroke) so a size edit is a
// single undo step, and an empty value clears the key.
function SizeField({
  label,
  value,
  onCommit,
  placeholder,
}: {
  label: string;
  value?: string;
  onCommit: (v: string) => void;
  placeholder?: string;
}) {
  const [local, setLocal] = React.useState(value ?? "");
  React.useEffect(() => {
    setLocal(value ?? "");
  }, [value]);
  const commit = () => {
    const next = local.trim();
    if (next !== (value ?? "")) onCommit(next);
  };
  return (
    <div>
      <label className="block text-[10px] tracking-wide text-muted-foreground uppercase mb-1">
        {label}
      </label>
      <input
        type="text"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        placeholder={placeholder}
        className="w-full bg-background border rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30"
      />
    </div>
  );
}

// A CSS <time> — the same shape the schema's DurationValue accepts. Checked
// here so a typo is caught in the panel: the value ends up inside motion.css's
// `animation` shorthand, and one malformed component invalidates the entire
// shorthand, which kills the animation outright rather than just ignoring the
// duration. Writing "1sec" would look like the motion had stopped working.
const CSS_TIME = /^\d+(\.\d+)?(ms|s)$/;

// Animation duration for the node's `motion`. Commit-on-blur/Enter and
// empty-clears mirror SizeField; the difference is the invalid-value state,
// which is held locally and NOT written to the schema — an invalid duration
// would be rejected by StyleSlot validation on save anyway, so it is better to
// show it red in the field than to hand the store a value it will refuse.
function DurationField({
  id,
  value,
  onCommit,
  disabled,
}: {
  id: string;
  value?: string;
  onCommit: (v: string) => void;
  disabled?: boolean;
}) {
  const [local, setLocal] = React.useState(value ?? "");
  React.useEffect(() => {
    setLocal(value ?? "");
  }, [value]);
  const invalid = local.trim() !== "" && !CSS_TIME.test(local.trim());
  const commit = () => {
    const next = local.trim();
    if (next !== "" && !CSS_TIME.test(next)) return;
    if (next !== (value ?? "")) onCommit(next);
  };
  return (
    <>
      <input
        id={id}
        type="text"
        value={local}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        placeholder="300ms · 1s · 0.25s"
        aria-invalid={invalid || undefined}
        spellCheck={false}
        className={`w-full bg-background border rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30 disabled:opacity-50 disabled:cursor-not-allowed ${
          invalid ? "border-destructive" : ""
        }`}
      />
      {invalid && (
        <p className="mt-1 text-[10px] text-destructive">
          Use a CSS time — 300ms, 1s, 0.25s
        </p>
      )}
    </>
  );
}

// Option values are TOKEN REFS (e.g. "spacing.4") that applyStyleSlot compiles
// to var(--token-spacing-4) — the CSS vars the canvas injects via compileTokens.
const BACKGROUND_OPTIONS = [
  { value: "", label: "(none)" },
  { value: "color.primary.500", label: "Primary · 500" },
  { value: "color.primary.100", label: "Primary · 100" },
  { value: "color.primary.50", label: "Primary · 50" },
  { value: "color.secondary.500", label: "Secondary · 500" },
  { value: "color.accent.500", label: "Accent · 500" },
];

// `<input type="color">` only accepts a literal "#rrggbb" — it silently resets
// to #000000 for "rebeccapurple", "rgb(59 130 246)" or a token ref. A 2D canvas
// context normalises any colour the browser understands into #rrggbb (or
// rgba(...) when it carries alpha), which is exactly the conversion we need and
// costs no dependency. Returns null when the string isn't a colour at all, so
// the caller can fall back rather than showing a misleading swatch.
let hexCanvasCtx: CanvasRenderingContext2D | null | undefined;
function cssColorToHex(value: string): string | null {
  if (typeof document === "undefined") return null;
  if (hexCanvasCtx === undefined) {
    hexCanvasCtx = document.createElement("canvas").getContext("2d");
  }
  const ctx = hexCanvasCtx;
  if (!ctx) return null;
  // fillStyle rejects invalid colours by KEEPING its previous value, so seed a
  // sentinel and check that the assignment actually moved it.
  ctx.fillStyle = "#000000";
  ctx.fillStyle = value;
  const first = ctx.fillStyle;
  ctx.fillStyle = "#ffffff";
  ctx.fillStyle = value;
  if (ctx.fillStyle !== first) return null; // value was rejected twice over
  return /^#[0-9a-f]{6}$/i.test(first) ? first : null;
}

// Background is the one style key that takes both a design token and a raw CSS
// value: tokens are the preferred path (they re-theme with the design system),
// raw colours are the escape hatch for one-off fills. The renderer decides
// between them with isColorTokenRef, so this control imports that same predicate
// instead of re-deriving the rule — a second copy would drift and the panel
// would disagree with what the canvas paints.
function BackgroundField({
  value,
  onCommit,
}: {
  value?: unknown;
  onCommit: (v: string) => void;
}) {
  // `background` may also hold the structured BackgroundT object (gradient,
  // image, pattern) which this control can't express; show it as empty rather
  // than stringifying it into "[object Object]" and offering that as a colour.
  const current = typeof value === "string" ? value : "";
  const isRaw = current !== "" && !isColorTokenRef(current);
  const [text, setText] = React.useState(current);
  React.useEffect(() => {
    setText(current);
  }, [current]);

  const swatch = (isRaw ? cssColorToHex(current) : null) ?? "#ffffff";

  // Dragging inside the OS colour picker fires a change per pixel of travel,
  // and editor-store pushes ONE undo entry per dispatch — committing each tick
  // would bury the previous state under a hundred history entries. A trailing
  // debounce collapses a drag into a single write while still updating the
  // canvas about as fast as the eye tracks it; releasing/leaving the input
  // flushes immediately so the last colour is never lost.
  const pending = React.useRef<number | null>(null);
  const commitDebounced = (v: string) => {
    setText(v);
    if (pending.current !== null) window.clearTimeout(pending.current);
    pending.current = window.setTimeout(() => {
      pending.current = null;
      onCommit(v);
    }, 200);
  };
  const flush = (v: string) => {
    if (pending.current !== null) {
      window.clearTimeout(pending.current);
      pending.current = null;
    }
    if (v !== current) onCommit(v);
  };
  React.useEffect(
    () => () => {
      if (pending.current !== null) window.clearTimeout(pending.current);
    },
    [],
  );

  // A raw colour has no matching <option>, which would leave the <select>
  // showing "(none)" and misrepresenting the node. Surface it as its own entry
  // so the dropdown always reflects the value actually in the schema.
  const options = isRaw
    ? [...BACKGROUND_OPTIONS, { value: current, label: `Custom · ${current}` }]
    : BACKGROUND_OPTIONS;

  return (
    <>
      <DropdownField
        value={current}
        onChange={(v) => flush(v)}
        options={options}
      />
      <div className="mx-3 mb-2 flex items-center gap-2">
        <label className="sr-only" htmlFor="bg-color-swatch">
          Background colour picker
        </label>
        <input
          id="bg-color-swatch"
          type="color"
          value={swatch}
          onChange={(e) => commitDebounced(e.target.value)}
          onBlur={(e) => flush(e.target.value)}
          title="Pick a background colour"
          className="h-8 w-9 shrink-0 cursor-pointer rounded-md border bg-background p-0.5"
        />
        <label className="sr-only" htmlFor="bg-color-text">
          Background colour or token
        </label>
        <input
          id="bg-color-text"
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={(e) => flush(e.target.value.trim())}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          placeholder="#3b82f6 · rebeccapurple · color.primary.500"
          spellCheck={false}
          className="w-full bg-background border rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30"
        />
      </div>
      <p className="px-3 -mt-1 mb-2 text-[10px] text-muted-foreground">
        Token ref, hex, CSS colour name, or any CSS fill
      </p>
    </>
  );
}

const SPACING_OPTIONS = [
  { value: "", label: "—" },
  { value: "spacing.2", label: "xs" },
  { value: "spacing.3", label: "sm" },
  { value: "spacing.4", label: "md" },
  { value: "spacing.6", label: "lg" },
  { value: "spacing.8", label: "xl" },
];

const RADIUS_OPTIONS = [
  { value: "", label: "—" },
  { value: "radius.sm", label: "sm" },
  { value: "radius.md", label: "md" },
  { value: "radius.lg", label: "lg" },
  { value: "radius.full", label: "full" },
];

const SHADOW_OPTIONS = [
  { value: "", label: "—" },
  { value: "shadow.sm", label: "sm" },
  { value: "shadow.md", label: "md" },
  { value: "shadow.lg", label: "lg" },
];

// Must match the schema's Motion enum (packages/schema style-slot.ts):
// z.enum(["none","fade-in","fade-up","stagger","slide-in"]). The old
// fast/base/slow values failed StyleSlot validation and got rejected.
const MOTION_OPTIONS = [
  { value: "", label: "(none)" },
  { value: "fade-in", label: "fade in" },
  { value: "fade-up", label: "fade up" },
  { value: "stagger", label: "stagger" },
  { value: "slide-in", label: "slide in" },
];

// The next three lists MUST mirror the unions in
// packages/library/src/theme/token-types.ts — components look the value up in a
// literal-keyed record (e.g. anchor-shared's `{ compact, comfortable, spacious }`)
// and an off-list value resolves to `undefined`, so the option silently applies
// nothing. "cozy", "rounded" and "pill" were exactly that: dead entries, while
// the real `spacious` and `round` were unreachable from the editor.
const DENSITY_OPTIONS = [
  { value: "compact", label: "compact" },
  { value: "comfortable", label: "comfortable" },
  { value: "spacious", label: "spacious" },
];

const ELEVATION_OPTIONS = [
  { value: "flat", label: "flat" },
  { value: "bordered", label: "bordered" },
  { value: "layered", label: "layered" },
  { value: "floating", label: "floating" },
];

const RADIUS_SCALE_OPTIONS = [
  { value: "sharp", label: "sharp" },
  { value: "soft", label: "soft" },
  { value: "round", label: "round" },
];

/**
 * Where each Design System control actually lives in the tokens artifact.
 *
 * These three controls used to read and write `tokens.system.<key>`, a group
 * NOTHING consumes — not the library, not the renderer, not the canvas. The
 * values persisted to tokens.custom.json and then sat there inert: picking
 * "compact" changed nothing on screen, and the panel displayed whatever was in
 * the dead group rather than the value components were really using.
 *
 * The real readers (packages/library/src/theme/tokens-context.tsx):
 *   useDensity()     tokens.density        (top-level scalar, default-tokens.ts:91)
 *   useElevation()   tokens.elevation      (top-level scalar, default-tokens.ts:92)
 *   useRadiusScale() tokens.radius.scale   (NESTED beside radius.sm/md/lg, :58)
 *
 * Note the asymmetry — two scalars and one nested leaf — which is why this is a
 * path table and not a `["system", key]` suffix.
 */
const DESIGN_SYSTEM_PATHS = {
  density:     ["density"],
  elevation:   ["elevation"],
  radiusScale: ["radius", "scale"],
} as const;

type DesignSystemKey = keyof typeof DESIGN_SYSTEM_PATHS;

// Displayed when the project overrides nothing. Sourced from defaultTokens
// rather than hardcoded so the panel can never claim a different starting point
// than the one components actually render with.
const DESIGN_SYSTEM_DEFAULTS: Record<DesignSystemKey, string> = {
  density:     defaultTokens.density,
  elevation:   defaultTokens.elevation,
  radiusScale: defaultTokens.radius.scale,
};

function getAtPath(obj: any, path: readonly string[]): unknown {
  return path.reduce((cur: any, key) => cur?.[key], obj);
}

/**
 * The actions for one Design System edit, including the one-time migration off
 * the dead `system` group.
 *
 * Existing projects (gh0mlpbp holds `{"density":"compact","elevation":"layered",
 * "radiusScale":"soft"}` there today) have real user choices under `system.*`.
 * Dropping the group without moving them would silently reset those projects, so
 * every sibling value that has no canonical counterpart yet is copied across in
 * the same edit. The legacy keys are then deleted rather than left in place: a
 * lingering `system.density` that disagrees with `tokens.density` is exactly the
 * kind of stale duplicate a later reader picks the wrong one of. The whole group
 * goes only when these three were all it contained — anything else in there
 * isn't ours to throw away.
 *
 * Returned as one batch so the edit plus its migration is a single undo step.
 */
function designSystemWrite(
  tokens: Record<string, any>,
  key: DesignSystemKey,
  value: string,
): EditorAction[] {
  const actions: EditorAction[] = [
    { type: "updateToken", path: [...DESIGN_SYSTEM_PATHS[key]], value },
  ];
  const legacy = (tokens.system ?? {}) as Record<string, string>;
  if (!tokens.system) return actions;

  for (const k of Object.keys(DESIGN_SYSTEM_PATHS) as DesignSystemKey[]) {
    if (k === key) continue;
    if (legacy[k] !== undefined && getAtPath(tokens, DESIGN_SYSTEM_PATHS[k]) === undefined) {
      actions.push({ type: "updateToken", path: [...DESIGN_SYSTEM_PATHS[k]], value: legacy[k] });
    }
  }

  const foreign = Object.keys(legacy).filter(
    (k) => !(k in DESIGN_SYSTEM_PATHS),
  );
  if (foreign.length === 0) {
    actions.push({ type: "removeToken", path: ["system"] });
  } else {
    for (const k of Object.keys(DESIGN_SYSTEM_PATHS) as DesignSystemKey[]) {
      if (legacy[k] !== undefined) actions.push({ type: "removeToken", path: ["system", k] });
    }
  }
  return actions;
}

function findNodeAndPage(
  artifacts: any,
  nodeId: string | null,
): { pageId: string; node: any } | null {
  if (!nodeId || !artifacts) return null;
  for (const [pageId, page] of Object.entries(artifacts.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return { pageId, node: n };
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

// Style tab — per-node StyleSlot controls + node-independent Design System.
export function StylePanel() {
  const artifacts = useEditorStore((s) => s.artifacts);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const selectedCount = useEditorStore((s) => s.selectedNodeIds.length);
  const dispatch = useEditorStore((s) => s.dispatch);
  const dispatchBatch = useEditorStore((s) => s.dispatchBatch);

  const hit = findNodeAndPage(artifacts, selectedNodeId);
  // Node-specific controls apply only to a single selected node. The Design
  // System block below is node-independent and always shows.
  const showNodeControls = !!hit && selectedCount <= 1;

  // Style controls write the node's top-level StyleSlot envelope (`node.style`)
  // — the field the renderer resolves via applyStyleSlot (structural nodes) and
  // the `style` prop (library nodes). Values are token refs (e.g. "spacing.4")
  // that applyStyleSlot compiles to var(--token-spacing-4). Writing node.props
  // (the old behaviour) had no effect because the renderer ignores props.style.
  const style = (hit?.node?.style ?? {}) as Record<string, string>;
  const writeStyle = (key: string, value: string) => {
    if (!hit) return;
    dispatch({
      type: "updateStyle",
      pageId: hit.pageId,
      nodeId: selectedNodeId!,
      styleKey: key,
      value: value || undefined,
    });
  };

  // Design-system tokens cascade from the tokens artifact, not per-node.
  const tokens = (artifacts?.tokens ?? {}) as Record<string, any>;
  const legacySystem = (tokens.system ?? {}) as Record<string, string>;
  const readSystem = (key: DesignSystemKey): string =>
    (getAtPath(tokens, DESIGN_SYSTEM_PATHS[key]) as string | undefined) ??
    legacySystem[key] ??
    DESIGN_SYSTEM_DEFAULTS[key];
  const writeSystemToken = (key: DesignSystemKey, value: string) => {
    dispatchBatch(designSystemWrite(tokens, key, value));
  };

  return (
    <div className="py-2">
      {!showNodeControls ? (
        <p className="px-3 py-3 text-sm text-muted-foreground">
          {selectedCount > 1
            ? `${selectedCount} nodes selected — select a single node to edit its style.`
            : "Select a node to edit its style."}
        </p>
      ) : (
      <>
      <span className={sectionLabelCls}>Size</span>
      <div className="px-3 mb-2 grid grid-cols-2 gap-2">
        <SizeField
          label="Width"
          value={(style as any).width}
          onCommit={(v) => writeStyle("width", v)}
          placeholder="auto"
        />
        <SizeField
          label="Height"
          value={(style as any).height}
          onCommit={(v) => writeStyle("height", v)}
          placeholder="auto"
        />
        <SizeField
          label="Min W"
          value={(style as any).minWidth}
          onCommit={(v) => writeStyle("minWidth", v)}
          placeholder="—"
        />
        <SizeField
          label="Max W"
          value={(style as any).maxWidth}
          onCommit={(v) => writeStyle("maxWidth", v)}
          placeholder="—"
        />
        <SizeField
          label="Min H"
          value={(style as any).minHeight}
          onCommit={(v) => writeStyle("minHeight", v)}
          placeholder="—"
        />
        <SizeField
          label="Max H"
          value={(style as any).maxHeight}
          onCommit={(v) => writeStyle("maxHeight", v)}
          placeholder="—"
        />
      </div>
      <p className="px-3 -mt-1 mb-2 text-[10px] text-muted-foreground">
        Any CSS unit — px, %, rem, auto
      </p>

      <span className={sectionLabelCls}>Background</span>
      <BackgroundField
        value={(style as any).background}
        onCommit={(v) => writeStyle("background", v)}
      />

      <span className={sectionLabelCls}>Padding</span>
      <DropdownField
        value={(style as any).padding}
        onChange={(v) => writeStyle("padding", v)}
        options={SPACING_OPTIONS}
      />

      <span className={sectionLabelCls}>Radius</span>
      <DropdownField
        value={(style as any).radius}
        onChange={(v) => writeStyle("radius", v)}
        options={RADIUS_OPTIONS}
      />

      <span className={sectionLabelCls}>Shadow</span>
      <DropdownField
        value={(style as any).shadow}
        onChange={(v) => writeStyle("shadow", v)}
        options={SHADOW_OPTIONS}
      />

      <span className={sectionLabelCls}>Motion</span>
      <DropdownField
        value={(style as any).motion}
        onChange={(v) => writeStyle("motion", v)}
        options={MOTION_OPTIONS}
      />
      {/* Disabled rather than hidden when no motion is picked: the field
          keeping its place stops the panel from reflowing every time the
          dropdown changes. A duration already stored stays stored — it is inert
          without a motion and comes back intact if the motion is re-enabled, so
          clearing it here would silently destroy the user's value. */}
      <div className="mx-3 mb-2">
        <label
          htmlFor="motion-duration"
          className="block text-[10px] tracking-wide text-muted-foreground uppercase mb-1"
        >
          Duration
        </label>
        <DurationField
          id="motion-duration"
          value={(style as any).motionDuration}
          onCommit={(v) => writeStyle("motionDuration", v)}
          disabled={!(style as any).motion || (style as any).motion === "none"}
        />
      </div>
      </>
      )}

      <div className="h-px bg-border mx-3 my-3" />

      <div className="px-3 mb-2">
        <h4 className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
          Design System
        </h4>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          System-wide · cascades from root node
        </p>
      </div>

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Density
      </div>
      <DropdownField
        value={readSystem("density")}
        onChange={(v) => writeSystemToken("density", v)}
        options={DENSITY_OPTIONS}
      />

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Elevation
      </div>
      <DropdownField
        value={readSystem("elevation")}
        onChange={(v) => writeSystemToken("elevation", v)}
        options={ELEVATION_OPTIONS}
      />

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Radius scale
      </div>
      <DropdownField
        value={readSystem("radiusScale")}
        onChange={(v) => writeSystemToken("radiusScale", v)}
        options={RADIUS_SCALE_OPTIONS}
      />
    </div>
  );
}
