"use client";
import * as React from "react";
import { useMemo } from "react";
import { defaultTokens } from "@tentoroforge/library";
import { useEditorStore } from "@/lib/editor-store";

const labelCls = "text-xs uppercase tracking-wide text-muted-foreground";

type TokenTree = Record<string, unknown>;

function isPlainObject(v: unknown): v is TokenTree {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Deep-merge the project's token OVERRIDES on top of the library defaults.
 *
 * WHY this merge lives here (display) and not in the store seed
 * (Canvas.tsx's setInitial): `artifacts.tokens` is what persistence.ts writes
 * verbatim to src/theme/tokens.custom.json on every autosave. If the merged
 * tree were seeded into the store, the first edit anywhere in the editor would
 * flush the ENTIRE default token set into the project's override file —
 * freezing today's defaults as permanent per-project overrides so future
 * defaultTokens changes could never reach the project again. Merging only for
 * render keeps `artifacts.tokens` an overrides-only document; dispatching
 * updateToken on a default-supplied path uses setNestedValue, which creates
 * exactly that one override.
 */
function deepMerge(base: TokenTree, override: TokenTree | undefined): TokenTree {
  if (!override) return base;
  const out: TokenTree = { ...base };
  for (const [k, v] of Object.entries(override)) {
    const prev = out[k];
    out[k] = isPlainObject(v) && isPlainObject(prev) ? deepMerge(prev, v) : v;
  }
  return out;
}

interface Leaf {
  /** Full dispatch path, e.g. ["color", "primary", "500"]. */
  path: string[];
  /** Human label — the path BELOW the section root, e.g. "duration.fast". */
  label: string;
  value: string;
}

/**
 * Flatten a token group to its scalar leaves, at any nesting depth.
 *
 * The canonical groups are NOT flat: spacing nests `semantic.page`, motion
 * nests `duration.fast` / `easing.standard`, and radius mixes scalars with the
 * `scale` knob. The previous flat Object.entries() render fed those nested
 * objects straight into an <input value={...}>, producing "[object Object]"
 * rows, and the `type="number"` inputs on spacing/radius rendered nothing at
 * all because the real values are CSS strings ("0.25rem"), not numbers.
 *
 * Object keys are deliberately NOT split on ".": some generated token files use
 * the legacy flat-map shape ({"color": {"primary.500": "#..."}}) that
 * compileTokens still honours. Splitting would make the edit write to
 * color.primary.500 while the display kept reading the untouched "primary.500"
 * key, so the edit would silently do nothing.
 */
function leaves(node: unknown, path: string[], depth: number): Leaf[] {
  if (node === null || node === undefined) return [];
  if (!isPlainObject(node)) {
    return [{ path, label: path.slice(depth).join("."), value: String(node) }];
  }
  return Object.entries(node).flatMap(([k, v]) => leaves(v, [...path, k], depth));
}

/** True when `path` is present in the project's own override document. */
function hasOverride(tree: TokenTree | undefined, path: string[]): boolean {
  let cur: unknown = tree;
  for (const seg of path) {
    if (!isPlainObject(cur) || !(seg in cur)) return false;
    cur = cur[seg];
  }
  return cur !== undefined;
}

const HEX = /^#[0-9a-f]{3,8}$/i;

/**
 * Text token field that commits on blur / Enter instead of per keystroke.
 *
 * WHY: `dispatch` is one undo entry AND one dirty transition per call
 * (editor-store.ts pushes `inverse` onto undoStack and sets isDirty, which
 * re-arms the 500 ms autosave in persistence.ts). Wiring `onChange` straight
 * to dispatch meant typing `1.25rem` produced SEVEN undo entries and a burst
 * of saves, burying the pre-edit value seven Ctrl-Zs deep. Same pattern as
 * SizeField in StylePanel.tsx: local state while typing, one dispatch when the
 * user is done. Escape abandons the edit and restores the committed value.
 */
function TokenTextInput({
  value,
  onCommit,
  className,
  ariaLabel,
}: {
  value: string;
  onCommit: (v: string) => void;
  className: string;
  ariaLabel: string;
}) {
  const [local, setLocal] = React.useState(value);
  React.useEffect(() => {
    setLocal(value);
  }, [value]);
  const commit = () => {
    if (local !== value) onCommit(local);
  };
  return (
    <input
      type="text"
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        else if (e.key === "Escape") {
          setLocal(value);
          (e.target as HTMLInputElement).blur();
        }
      }}
      className={className}
      aria-label={ariaLabel}
    />
  );
}

/**
 * Colour swatch that collapses a picker DRAG into a single write.
 *
 * WHY: `<input type="color">` fires change once per pixel of travel inside the
 * OS picker — roughly a hundred dispatches, i.e. a hundred undo entries and a
 * hundred re-armed autosaves, for one colour choice. A 200 ms trailing debounce
 * collapses the drag while still repainting the canvas about as fast as the eye
 * tracks it; blur flushes immediately so the last colour is never lost. Mirrors
 * BackgroundField in StylePanel.tsx, which solved exactly this for node styles.
 */
function TokenColorInput({
  value,
  onCommit,
  className,
  ariaLabel,
}: {
  value: string;
  onCommit: (v: string) => void;
  className: string;
  ariaLabel: string;
}) {
  const [local, setLocal] = React.useState(value);
  React.useEffect(() => {
    setLocal(value);
  }, [value]);
  const pending = React.useRef<number | null>(null);
  const clear = () => {
    if (pending.current !== null) {
      window.clearTimeout(pending.current);
      pending.current = null;
    }
  };
  React.useEffect(() => clear, []);
  return (
    <input
      type="color"
      value={local}
      onChange={(e) => {
        const v = e.target.value;
        setLocal(v);
        clear();
        pending.current = window.setTimeout(() => {
          pending.current = null;
          if (v !== value) onCommit(v);
        }, 200);
      }}
      onBlur={() => {
        clear();
        if (local !== value) onCommit(local);
      }}
      className={className}
      aria-label={ariaLabel}
    />
  );
}

export function TokenEditor() {
  const tokens = useEditorStore(s => s.artifacts?.tokens as TokenTree | undefined);
  const dispatch = useEditorStore(s => s.dispatch);

  // ROOT CAUSE this fixes: the panel used to render `tokens.color` etc.
  // straight out of the store, and the store is seeded (Canvas.tsx) from ONLY
  // src/theme/tokens.custom.json. That file is the project's OVERRIDE layer —
  // for gh0mlpbp it is the untouched generator stub
  // {"color":{},"typography":{},...}. So every section was empty while the
  // guard below still passed (the object exists, its groups are just empty),
  // which is exactly the "headings but no rows, and no 'No tokens loaded.'"
  // symptom. The tokens the project actually renders with are
  // merge(defaultTokens, custom) — see the generated app's
  // src/theme/tokens.server.ts — so the panel must show that same merge.
  const merged = useMemo(
    () => deepMerge(defaultTokens as unknown as TokenTree, tokens),
    [tokens],
  );

  if (!tokens) {
    return <div className="p-4 text-sm text-muted-foreground">No tokens loaded.</div>;
  }

  // Every value written back is a STRING. The old spacing/radius handlers ran
  // Number(value) over CSS lengths, so editing "1rem" stored NaN — and
  // JSON.stringify(NaN) is `null`, which would have written a null token into
  // tokens.custom.json and broken the generated app's CSS-var compile.
  const update = (path: string[], value: string) =>
    dispatch({ type: "updateToken", path, value });

  return (
    <div className="p-3 space-y-4">
      <ColorSection
        groups={merged.color}
        overrides={tokens}
        onUpdate={update}
        onRemove={(path) => dispatch({ type: "removeToken", path })}
      />

      <FlatSection title="Spacing" node={merged.spacing} root={["spacing"]} onUpdate={update} />
      <FlatSection title="Radius" node={merged.radius} root={["radius"]} onUpdate={update} />

      <TypographySection typography={merged.typography} onUpdate={update} />

      <FlatSection title="Shadow" node={merged.shadow} root={["shadow"]} onUpdate={update} />
      <FlatSection title="Motion" node={merged.motion} root={["motion"]} onUpdate={update} />
    </div>
  );
}

// ----- Sub-components -----

interface ColorSectionProps {
  groups: unknown;
  overrides: TokenTree | undefined;
  onUpdate: (path: string[], value: string) => void;
  onRemove: (path: string[]) => void;
}

function ColorSection({ groups, overrides, onUpdate, onRemove }: ColorSectionProps) {
  const entries = isPlainObject(groups) ? Object.entries(groups) : [];
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>Color</legend>
      {entries.map(([group, swatches]) => (
        <div key={group} className="space-y-1">
          <div className="text-xs font-medium">{group}</div>
          {leaves(swatches, ["color", group], 2).map((leaf) => {
            const key = leaf.path.join(".");
            // Only overrides can be removed: removeToken deletes from
            // `artifacts.tokens`, and a library default has no entry there, so
            // the × would look broken (row stays after the click).
            const removable = hasOverride(overrides, leaf.path);
            return (
              <div key={key} className="flex gap-2 items-center">
                <TokenColorInput
                  value={HEX.test(leaf.value) ? leaf.value : "#000000"}
                  onCommit={(v) => onUpdate(leaf.path, v)}
                  className="h-6 w-12 border rounded cursor-pointer"
                  ariaLabel={key}
                />
                <span className="text-xs flex-1 truncate" title={`${key} = ${leaf.value}`}>
                  {leaf.label}: {leaf.value}
                </span>
                {removable && (
                  <button
                    onClick={() => onRemove(leaf.path)}
                    className="text-xs text-muted-foreground hover:text-destructive"
                    title="Remove override"
                    aria-label={`Remove ${key}`}
                  >
                    ×
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </fieldset>
  );
}

interface FlatSectionProps {
  title: string;
  node: unknown;
  root: string[];
  onUpdate: (path: string[], value: string) => void;
}

function FlatSection({ title, node, root, onUpdate }: FlatSectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>{title}</legend>
      {leaves(node, root, root.length).map((leaf) => (
        <label key={leaf.path.join(".")} className="flex gap-2 items-center text-xs">
          <span className="w-20 shrink-0 truncate" title={leaf.label}>{leaf.label}</span>
          <TokenTextInput
            value={leaf.value}
            onCommit={(v) => onUpdate(leaf.path, v)}
            className="flex-1 min-w-0 border rounded px-2 py-0.5 bg-background"
            ariaLabel={leaf.path.join(".")}
          />
        </label>
      ))}
    </fieldset>
  );
}

interface TypographySectionProps {
  typography: unknown;
  onUpdate: (path: string[], value: string) => void;
}

function TypographySection({ typography, onUpdate }: TypographySectionProps) {
  const t = isPlainObject(typography) ? typography : {};
  // The canonical group is `typography.font` (see packages/library
  // default-tokens.ts and every generated tokens.custom.json). This panel read
  // `typography.fontFamily`, a key nothing writes, so the Font family list was
  // empty even for projects with a fully populated token file. `fontFamily` is
  // kept as a fallback for any hand-edited file that used it.
  const fontKey = isPlainObject(t.font) ? "font" : "fontFamily";
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>Typography</legend>
      <div className="space-y-1">
        <div className="text-xs font-medium">Font family</div>
        {leaves(t[fontKey], ["typography", fontKey], 2).map((leaf) => (
          <label key={leaf.path.join(".")} className="flex gap-2 items-center text-xs">
            <span className="w-20 shrink-0 truncate" title={leaf.label}>{leaf.label}</span>
            <TokenTextInput
              value={leaf.value}
              onCommit={(v) => onUpdate(leaf.path, v)}
              className="flex-1 min-w-0 border rounded px-2 py-0.5 bg-background font-mono text-[10px]"
              ariaLabel={leaf.path.join(".")}
            />
          </label>
        ))}
      </div>
      <div className="space-y-1">
        {/* Not "(px)": the scale values are CSS lengths ("2rem"), and the old
            number input silently rendered blank for every one of them. */}
        <div className="text-xs font-medium">Scale</div>
        {leaves(t.scale, ["typography", "scale"], 2).map((leaf) => (
          <label key={leaf.path.join(".")} className="flex gap-2 items-center text-xs">
            <span className="w-20 shrink-0 truncate" title={leaf.label}>{leaf.label}</span>
            <TokenTextInput
              value={leaf.value}
              onCommit={(v) => onUpdate(leaf.path, v)}
              className="flex-1 min-w-0 border rounded px-2 py-0.5 bg-background"
              ariaLabel={leaf.path.join(".")}
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
