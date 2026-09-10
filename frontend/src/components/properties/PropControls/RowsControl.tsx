"use client";
import * as React from "react";
import { RawJsonEditor } from "./RawJsonEditor";
import { looksLikeRoute, useRouteHints } from "./RouteControl";

const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";
const btnCls =
  "border rounded px-1.5 py-0.5 text-xs leading-none bg-muted/40 hover:bg-muted " +
  "disabled:opacity-30 disabled:hover:bg-muted/40";

/**
 * Repeating-row editor for option-shaped arrays — Select/RadioGroup/MultiSelect
 * `options`, FilterBar `chips`, and the ~26 other array props the registry now
 * types `array` instead of hiding behind an ActionPicker.
 *
 * WHY it exists: `control:"json"` made those props EDITABLE, which is a real fix,
 * but the thing being edited is nearly always a list of `{value,label}` and a raw
 * textarea makes the user hand-balance braces to add one entry — and a single
 * typo silently refuses the whole commit. Rows with add/remove/reorder turn that
 * into three clicks.
 *
 * WHY it sniffs the shape instead of being told: nothing in PropDescriptor says
 * which key holds the value (`value` / `key` / `id`) or whether the items are
 * objects at all (`Breadcrumb.items` is `{label,href}`, some props are plain
 * strings), and the descriptor type is owned by another package. The rule below
 * is deliberately conservative: anything it cannot read with confidence falls
 * through to the raw JSON editor UNTOUCHED, because the one thing a "helpful"
 * editor must never do to a prop it misread is rewrite it.
 */

type PlainObject = Record<string, unknown>;

/** Keys that, in this registry, carry a row's stored value. Order = preference. */
const VALUE_KEYS = ["value", "key", "id"] as const;
/** Keys that carry a row's human-facing text. Order = preference. */
const LABEL_KEYS = ["label", "name", "title", "text"] as const;

export type RowShape =
  // `valueKey` is the row's FIRST editable field and `labelKey` its second.
  // It is null when the rows carry no identity key at all — a breadcrumb crumb
  // is `{label, href}` — in which case the label takes the first field and the
  // row's other shared key, if it has one, takes the second.
  | { kind: "objects"; valueKey: string | null; labelKey: string | null; extraKeys: string[] }
  | { kind: "strings" }
  | { kind: "unknown"; reason: string };

function isPlainObject(v: unknown): v is PlainObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** First key from `candidates` that every row carries. */
function sharedKey(rows: PlainObject[], candidates: readonly string[]): string | null {
  for (const k of candidates) {
    if (rows.every((r) => k in r)) return k;
  }
  return null;
}

export function analyzeRows(value: unknown): RowShape {
  // An unset prop is an empty list, not an unreadable value: the user needs
  // "Add row", not a JSON box, to fill in a prop that has never been set.
  if (value === undefined || value === null) {
    return { kind: "objects", valueKey: "value", labelKey: "label", extraKeys: [] };
  }
  if (!Array.isArray(value)) {
    return { kind: "unknown", reason: "not a list" };
  }
  // An empty list has no shape to read either. Assume the registry-wide
  // default — {value,label} — so "Add row" produces the shape the components
  // actually validate against instead of an empty object nothing renders.
  if (value.length === 0) {
    return { kind: "objects", valueKey: "value", labelKey: "label", extraKeys: [] };
  }
  if (value.every((v) => typeof v === "string")) return { kind: "strings" };
  if (value.every(isPlainObject)) {
    const rows = value as PlainObject[];
    const identityKey = sharedKey(rows, VALUE_KEYS);
    const labelKey = sharedKey(rows, LABEL_KEYS);
    // An identity key is not what makes a row editable — having a field the
    // user can read is. Rows shaped `{label, href}` (every breadcrumb crumb,
    // and the reason this loosened) used to fall through to a raw JSON
    // textarea reading "no value / key / id on every row", which named the
    // thing the row lacked instead of editing the two fields it has.
    if (!identityKey && !labelKey) {
      return { kind: "unknown", reason: "no value / key / id / label on every row" };
    }
    // Every key present on EVERY row, in first-row order — the ones it is safe
    // to show a field for. Keys only some rows carry stay in the JSON.
    const shared = Object.keys(rows[0]).filter((k) => rows.every((r) => k in r));
    const valueKey =
      identityKey ?? shared.find((k) => k !== labelKey) ?? null;
    const extraKeys = Array.from(
      new Set(rows.flatMap((r) => Object.keys(r))),
    ).filter((k) => k !== valueKey && k !== labelKey);
    return { kind: "objects", valueKey, labelKey, extraKeys };
  }
  return { kind: "unknown", reason: "rows are not all the same shape" };
}

function newRow(shape: RowShape): unknown {
  if (shape.kind === "strings") return "";
  if (shape.kind === "objects") {
    const row: PlainObject = {};
    if (shape.valueKey) row[shape.valueKey] = "";
    if (shape.labelKey) row[shape.labelKey] = "";
    return row;
  }
  return "";
}

/**
 * A text field whose edits stay local until blur.
 *
 * Same reason JsonControl commits on blur: every onChange here is a dispatch,
 * and editor-store pushes one undo entry per dispatch, so a per-keystroke commit
 * would make Ctrl+Z walk back through the user's typing one letter at a time.
 * Escape restores the committed text, matching the JSON editor.
 */
function RowField({
  ariaLabel, value, onCommit, placeholder,
}: {
  ariaLabel: string;
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => { setDraft(value); }, [value]);
  // A cell holding a destination gets the project's real routes as
  // suggestions and a notice when it reaches no page — the same treatment a
  // whole route-valued prop gets, decided by the VALUE's shape so it applies
  // to a breadcrumb `href`, a menu row's `to`, or anything added later. The
  // commit-on-blur contract above is untouched.
  const { listId, datalist, warning } = useRouteHints(draft);
  const isRoute = looksLikeRoute(draft);
  return (
    <>
      <input
        type="text"
        aria-label={ariaLabel}
        list={isRoute ? listId : undefined}
        className="border rounded px-1.5 py-0.5 text-xs bg-background min-w-0 flex-1"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { if (draft !== value) onCommit(draft); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setDraft(value);
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
      {isRoute ? datalist : null}
      {isRoute ? warning : null}
    </>
  );
}

export function RowsControl({
  label, value, onChange,
}: {
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const shape = React.useMemo(() => analyzeRows(value), [value]);
  const rows: unknown[] = Array.isArray(value) ? value : [];
  const [rawMode, setRawMode] = React.useState(false);

  // Shapes the sniffer could not read are never rewritten — the user gets the
  // JSON they already have, plus the reason the row editor stood down.
  if (shape.kind === "unknown" || rawMode) {
    return (
      // A <div>, not a <label>: the escape hatch holds a button, and a button
      // inside a <label> re-targets its clicks at the labelled control.
      <div className={labelCls}>
        <span className={labelText}>{label}</span>
        <RawJsonEditor label={label} value={value} onChange={onChange} placeholder='[{"value": "one", "label": "Option one"}]' />
        {shape.kind === "unknown" ? (
          <span className="text-[11px] text-muted-foreground">
            Editing as JSON — {shape.reason}.
          </span>
        ) : (
          <button type="button" className={`${btnCls} self-start`} onClick={() => setRawMode(false)}>
            Edit as rows
          </button>
        )}
      </div>
    );
  }

  const write = (next: unknown[]) => onChange(next);
  const setRow = (i: number, row: unknown) => {
    const next = rows.slice();
    next[i] = row;
    write(next);
  };
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= rows.length) return;
    const next = rows.slice();
    [next[i], next[j]] = [next[j], next[i]];
    write(next);
  };

  return (
    <div className={labelCls}>
      <span className={labelText}>{label}</span>
      <ul className="flex flex-col gap-1 list-none p-0 m-0">
        {rows.map((row, i) => {
          const obj = isPlainObject(row) ? row : null;
          // Which keys get a field, and in which order. A row with an identity
          // key leads with it (`{value,label}` — the registry-wide shape); a
          // row without one leads with the label, because that is the part the
          // user reads (`{label,href}`). Each field is named after the key it
          // edits, so the second box on a crumb says `href`, not "value".
          const keys: Array<string | null> =
            shape.kind === "strings"
              ? [null]
              : (shape.valueKey && (VALUE_KEYS as readonly string[]).includes(shape.valueKey)
                  ? [shape.valueKey, shape.labelKey]
                  : [shape.labelKey, shape.valueKey]
                ).filter((k) => k !== null);
          return (
            <li key={i} className="flex items-center gap-1">
              {keys.map((key, fieldIndex) => {
                const name = key ?? "value";
                const text =
                  key === null
                    ? String(row ?? "")
                    : String((obj?.[key] as unknown) ?? "");
                return (
                  <RowField
                    key={name}
                    ariaLabel={
                      // The first field keeps the historic "…row N value"
                      // wording whatever key it edits, so existing callers and
                      // tests still find it; later fields are named for real.
                      fieldIndex === 0
                        ? `${label} row ${i + 1} value`
                        : `${label} row ${i + 1} ${name}`
                    }
                    value={text}
                    placeholder={name}
                    onCommit={(v) =>
                      setRow(i, key === null ? v : { ...(obj ?? {}), [key]: v })
                    }
                  />
                );
              })}
              <button
                type="button" className={btnCls} disabled={i === 0}
                aria-label={`Move ${label} row ${i + 1} up`}
                onClick={() => move(i, -1)}
              >↑</button>
              <button
                type="button" className={btnCls} disabled={i === rows.length - 1}
                aria-label={`Move ${label} row ${i + 1} down`}
                onClick={() => move(i, 1)}
              >↓</button>
              <button
                type="button" className={btnCls}
                aria-label={`Remove ${label} row ${i + 1}`}
                onClick={() => write(rows.filter((_, k) => k !== i))}
              >✕</button>
            </li>
          );
        })}
      </ul>
      {rows.length === 0 && (
        <span className="text-[11px] text-muted-foreground italic">No rows yet.</span>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button" className={btnCls}
          aria-label={`Add row to ${label}`}
          onClick={() => write([...rows, newRow(shape)])}
        >+ Add row</button>
        <button
          type="button"
          className="text-[11px] underline text-muted-foreground hover:text-foreground"
          onClick={() => setRawMode(true)}
        >
          Edit as JSON
        </button>
      </div>
      {shape.kind === "objects" && shape.extraKeys.length > 0 && (
        // Say so out loud: the row editor shows two of the row's keys and writes
        // the rest back untouched, so the user does not conclude the other keys
        // were dropped and go re-add them by hand.
        <span className="text-[11px] text-muted-foreground">
          Also keeps: {shape.extraKeys.join(", ")} (edit those in JSON).
        </span>
      )}
    </div>
  );
}
