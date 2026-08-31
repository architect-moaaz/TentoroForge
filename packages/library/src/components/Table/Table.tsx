"use client";
import * as React from "react";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";
import { useContext } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { WorkflowDispatcherContext, useNavigator } from "@tentoroforge/renderer";
import { resolveStyle } from "../../style/resolveStyle";
import { ensureHumanLabel } from "../../utils/humanizeLabel";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";
import { fallbackDispatch } from "../../util/fallbackDispatch";
import type { ColumnDef, RowActionDef } from "./Table.schema";
import { SCROLL_X, scrollEdgeStyle } from "../../style/scroll";

/**
 * Modern, interactive data table.
 *
 * Data mode (`rows="{{items}}"` + `columns`): renders a card-framed table with a
 * toolbar (title + global search), sortable headers, smart cell formatting
 * (status badges, dates, booleans, right-aligned numbers), optional row selection,
 * per-row actions, clickable rows, and pagination — all zero-config, inferred from
 * the values when column hints aren't supplied.
 *
 * Legacy mode (`children`, e.g. a Repeat filling <tr>s): renders the same chrome
 * around the provided rows without the interactive layer.
 *
 * Painted from design tokens so it matches the generated app's theme.
 */

type Density = "compact" | "comfortable" | "spacious";
const PAD: Record<Density, string> = { compact: "px-3 py-1.5", comfortable: "px-4 py-2.5", spacious: "px-6 py-3.5" };
const TXT: Record<Density, string> = { compact: "text-xs", comfortable: "text-sm", spacious: "text-base" };

export interface TableProps {
  columns: ColumnDef[];
  caption?: string;
  title?: string;
  rows?: unknown;
  data?: unknown;
  searchable?: boolean;
  pageSize?: number;
  selectable?: boolean;
  rowActions?: RowActionDef[];
  rowHref?: string;
  striped?: boolean;
  stickyHeader?: boolean;
  emptyText?: string;
  /** FIX-4 empty-state — a hint sentence below the empty title. */
  emptyDescription?: string;
  /** FIX-4 empty-state — CTA rendered under the description. Wire a
   *  `navigate` (destination route) or `workflow` (dispatch key). */
  emptyAction?: { label: string; navigate?: string; workflow?: string };
  density?: Density;
  /** Loading skeleton — matches final layout dimensions so the row area
   *  doesn't reflow when data arrives. Root-cause fix for CLS class. */
  isLoading?: boolean;
  skeletonRows?: number;
  className?: string;
  style?: StyleSlotT;
  children?: React.ReactNode;
  /** Test injection only — allows bypassing context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void | Promise<void>;

  // ── Spec E Wave 3 — inline editing ────────────────────────────────────
  /** Column keys that become click-to-edit inputs. */
  editableColumns?: string[];
  /** Optional workflow to fire on "Save all". Row patches are emitted
   *  as `forge:row:update` events either way. */
  editSaveWorkflow?: string;
}

const STATUS_COLORS: Record<string, string> = {
  active: "#10B981", enabled: "#10B981", approved: "#10B981", completed: "#10B981", done: "#10B981",
  paid: "#10B981", success: "#10B981", available: "#10B981", open: "#3B82F6", confirmed: "#3B82F6",
  inprogress: "#3B82F6", processing: "#3B82F6", pending: "#F59E0B", review: "#8B5CF6", onhold: "#F59E0B",
  draft: "#94A3B8", inactive: "#94A3B8", disabled: "#94A3B8", closed: "#64748B", cancelled: "#EF4444",
  canceled: "#EF4444", failed: "#EF4444", rejected: "#EF4444", blocked: "#EF4444", overdue: "#EF4444",
  occupied: "#F59E0B", dirty: "#EF4444", clean: "#10B981", maintenance: "#8B5CF6",
  low: "#10B981", medium: "#F59E0B", high: "#EF4444", urgent: "#DC2626", critical: "#DC2626",
};
const PALETTE = ["#64748B", "#3B82F6", "#8B5CF6", "#F59E0B", "#10B981", "#EC4899", "#14B8A6"];
const norm = (s: unknown) => String(s ?? "").trim().toLowerCase().replace(/[\s_-]+/g, "");

function badgeColor(v: string): string {
  const n = norm(v);
  if (STATUS_COLORS[n]) return STATUS_COLORS[n];
  let h = 0;
  for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function humanize(key: string): string {
  const s = String(key ?? "").replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  return s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : "";
}
function applyTemplate(tpl: string, rec: Record<string, unknown>): string {
  // Accept both the schema's Mustache-style {{id}} (what the generator emits for
  // rowHref / navigate) and bare {id}. Matching only {id} turned "/x/{{id}}" into
  // "/x/{123}" — stray braces that broke the detail-drawer route.
  return tpl.replace(/\{\{?\s*(\w+)\s*\}\}?/g, (_m, k) => String(rec[k] ?? ""));
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?/;
const STATUSY = /^(status|state|stage|phase|type|kind|role|priority|severity|category|tier)$/i;
// Absolute http(s) URL OR the app's own /api/files/<uuid> shape (which
// resolves to bytes at runtime — treat as an image if the column name says
// image, otherwise as a URL).
const URL_RE = /^https?:\/\/[^\s]+$/i;
const API_FILE_RE = /^\/api\/files\/[a-z0-9-]+/i;
// File extensions the browser can render inline.
const IMG_EXT_RE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)(\?.*)?$/i;
// Column names that hint at image content even when the value doesn't end in
// an extension (e.g. presigned S3 URLs, forge_files ids).
const IMG_KEY_RE = /(^|_)(image|photo|thumbnail|thumb|avatar|logo|picture|icon)(_?url)?$/i;

function looksLikeUrl(v: unknown): boolean {
  return typeof v === "string" && (URL_RE.test(v) || API_FILE_RE.test(v));
}

/** Decide how to render a column's cells from an explicit hint or the values. */
function inferFormat(col: ColumnDef, sample: unknown[]): NonNullable<ColumnDef["format"]> {
  if (col.format) return col.format;
  if (STATUSY.test(col.key)) return "badge";
  const vals = sample.filter((v) => v !== null && v !== undefined && v !== "");
  if (vals.length === 0) return "text";
  if (vals.every((v) => typeof v === "boolean")) return "boolean";
  if (vals.every((v) => typeof v === "number")) return "number";
  if (vals.every((v) => v instanceof Date || (typeof v === "string" && ISO_DATE.test(v)))) return "date";
  const strs = vals.filter((v) => typeof v === "string") as string[];
  if (strs.length === vals.length && strs.every(looksLikeUrl)) {
    // The column is a URL. If it's clearly an image (ext or key name),
    // render inline thumbnails; otherwise render clickable link.
    if (IMG_KEY_RE.test(col.key) || strs.every((s) => IMG_EXT_RE.test(s) || API_FILE_RE.test(s))) return "image";
    return "url";
  }
  if (strs.length === vals.length) {
    const uniq = new Set(strs.map(norm));
    if (uniq.size <= Math.min(6, Math.ceil(vals.length / 2)) && strs.every((s) => s.length <= 24)) return "badge";
  }
  return "text";
}

function urlHostname(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
}

function asDate(v: unknown): Date | null {
  if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
  if (typeof v === "string" && ISO_DATE.test(v)) { const d = new Date(v); return isNaN(d.getTime()) ? null : d; }
  return null;
}

/**
 * SensitiveCell — Slice-4 encrypt-at-rest rendering.
 *
 * The Cell renders the pre-computed masked value the server already put
 * in `<key>`. When a `sensitiveEndpoint` is set and the caller's role
 * may unmask (`canUnmask`), an eye button appears. Clicking fetches
 * `<endpoint>/<rowId>?unmask=<key>` and swaps in the returned plaintext
 * for THIS row only. The click is stopPropagation'd so the row-href
 * navigation doesn't fire.
 *
 * The endpoint call is deliberately narrow (one row, one column at a
 * time) so a viewer can't accidentally batch-unmask an entire table with
 * one click. The server audits every unmask; the client doesn't need to.
 */
function SensitiveCell({
  value, col, rowId,
}: { value: unknown; col: ColumnDef; rowId: string | number | undefined }) {
  const [revealed, setRevealed] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const canUnmask = col.canUnmask === true && !!col.sensitiveEndpoint && rowId != null;

  const display = revealed ?? (value == null ? "" : String(value));
  const shown = display === "" ? "—" : display;

  const toggle = React.useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (revealed !== null) { setRevealed(null); return; }
    if (!col.sensitiveEndpoint || rowId == null) return;
    setLoading(true);
    try {
      const url = `${col.sensitiveEndpoint.replace(/\/$/, "")}/${encodeURIComponent(String(rowId))}?unmask=${encodeURIComponent(col.key)}`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return;
      const body = await res.json();
      const v = body?.[col.key];
      if (typeof v === "string") setRevealed(v);
    } catch {
      /* silently keep the mask — network errors shouldn't leak data */
    } finally {
      setLoading(false);
    }
  }, [revealed, col.sensitiveEndpoint, col.key, rowId]);

  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums" data-sensitive="">
      <span className={display === "" ? "text-muted-foreground/50" : ""}>{shown}</span>
      {canUnmask && (
        <button
          type="button"
          onClick={toggle}
          className="inline-flex items-center justify-center rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
          disabled={loading}
          aria-label={revealed ? "Hide sensitive value" : "Reveal sensitive value"}
          aria-pressed={revealed !== null}
          data-testid="sensitive-toggle"
        >
          {/* Minimal inline SVG so the Table has no icon-library dep. */}
          {revealed !== null ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M17.94 17.94A10 10 0 0 1 12 20c-7 0-10-8-10-8a17.34 17.34 0 0 1 3.94-5.06M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 8 10 8a17.28 17.28 0 0 1-2.4 3.32M1 1l22 22M14.12 14.12A3 3 0 1 1 9.88 9.88" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M1 12s3-8 11-8 11 8 11 8-3 8-11 8S1 12 1 12z" /><circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
      )}
    </span>
  );
}

function Cell({ value, fmt }: { value: unknown; fmt: NonNullable<ColumnDef["format"]> }) {
  if (fmt === "sensitive") {
    // Slice-4: the SensitiveCell branch requires per-cell context (col +
    // rowId), so a caller that wants the eye toggle uses SensitiveCell
    // directly in the row loop below. This branch handles the case where
    // a Cell was invoked with `fmt:"sensitive"` but no context — render
    // the mask as plain text.
    if (value === null || value === undefined || value === "") return <span className="text-muted-foreground/50">—</span>;
    return <span className="tabular-nums" data-sensitive="">{String(value)}</span>;
  }
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground/50">—</span>;
  if (fmt === "boolean" || typeof value === "boolean") {
    return value
      ? <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary text-[11px]">✓</span>
      : <span className="text-muted-foreground/50">—</span>;
  }
  if (fmt === "date" || fmt === "datetime") {
    const d = asDate(value);
    // Pin the locale so the server (Node, whatever its OS locale) and the client
    // (the user's browser locale) format IDENTICALLY. A bare toLocaleDateString()
    // renders e.g. "01/06/2024" on the server and "6/1/2024" in a US browser,
    // which fails React hydration and leaves the whole page non-interactive.
    if (d) return <span>{fmt === "datetime" ? d.toLocaleString("en-US") : d.toLocaleDateString("en-US")}</span>;
  }
  if (fmt === "currency") {
    const n = Number(value);
    // Pinned locale — same hydration-stability reason as dates above.
    if (!isNaN(n)) return <span className="tabular-nums">{n.toLocaleString("en-US", { style: "currency", currency: "USD" })}</span>;
  }
  if (fmt === "number") return <span className="tabular-nums">{String(value)}</span>;
  if (fmt === "badge") {
    const c = badgeColor(String(value));
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
        style={{ background: `${c}1A`, color: c }}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
        {humanize(String(value))}
      </span>
    );
  }
  if (fmt === "url") {
    const url = String(value);
    // stopPropagation so clicking the link doesn't ALSO fire the rowHref
    // navigation on the surrounding <tr>. The label is the hostname —
    // "amazon.com" is more scannable than the full URL, tooltip has the rest.
    return (
      <a href={url} target="_blank" rel="noreferrer noopener"
        onClick={(e) => e.stopPropagation()}
        className="text-primary hover:underline max-w-[22rem] inline-block truncate align-bottom"
        title={url}>
        {urlHostname(url)}
      </a>
    );
  }
  if (fmt === "image") {
    // Small thumbnail. Same click-stopPropagation as URLs.
    return (
      <img src={String(value)} alt=""
        onClick={(e) => e.stopPropagation()}
        className="h-10 w-10 rounded-md object-cover border border-border/60" />
    );
  }
  const s = typeof value === "object" ? JSON.stringify(value) : String(value);
  return <span className="block max-w-[28rem] truncate" title={s}>{s}</span>;
}

function SortIcon({ dir }: { dir: "asc" | "desc" | null }) {
  return (
    <span className="ms-1 inline-flex flex-col leading-none text-[8px]">
      <span className={dir === "asc" ? "text-foreground" : "text-muted-foreground/40"}>▲</span>
      <span className={dir === "desc" ? "text-foreground" : "text-muted-foreground/40"}>▼</span>
    </span>
  );
}

/**
 * EditableCell — Spec E Wave 3 inline-edit input. Auto-focuses on
 * mount, commits on blur or Enter, reverts on Escape. Chooses input
 * type from the inferred cell format so numeric columns get a number
 * input and dates get a date input.
 */
function EditableCell({
  initial,
  format,
  onCommit,
  onCancel,
}: {
  initial: unknown;
  format?: NonNullable<ColumnDef["format"]>;
  onCommit: (v: unknown) => void;
  onCancel: () => void;
}): React.ReactElement {
  const [v, setV] = React.useState<string>(initial == null ? "" : String(initial));
  const ref = React.useRef<HTMLInputElement | null>(null);
  React.useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  const type =
    format === "number" || format === "currency" ? "number"
    : format === "date" ? "date"
    : format === "datetime" ? "datetime-local"
    : "text";
  const parse = (raw: string): unknown => {
    if (type === "number") {
      if (raw === "") return null;
      const n = Number(raw);
      return isNaN(n) ? raw : n;
    }
    return raw;
  };
  return (
    <input
      ref={ref}
      type={type}
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => onCommit(parse(v))}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); onCommit(parse(v)); }
        else if (e.key === "Escape") { e.preventDefault(); onCancel(); }
      }}
      className="w-full rounded border border-primary/60 bg-background px-1.5 py-0.5 text-sm text-foreground outline-none"
      data-forge-editable-cell
    />
  );
}

export function Table(props: TableProps) {
  const {
    columns, caption, title, rows, data, rowActions, rowHref, emptyText,
    striped = true, stickyHeader = true, className, style, children,
  } = props;
  const densityCtx = useDensity();
  const nav = useNavigator();
  const density = (props.density ?? densityCtx) as Density;
  const pad = PAD[density];
  const txt = TXT[density];

  const records = (Array.isArray(rows) ? rows : Array.isArray(data) ? data : null) as Record<string, unknown>[] | null;
  const dataMode = !!records && !children;
  const searchable = props.searchable ?? dataMode;
  const selectable = props.selectable ?? false;

  const [query, setQuery] = React.useState("");
  const [sortKey, setSortKey] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");
  const [page, setPage] = React.useState(0);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  // Spec E Wave 3 — inline edits keyed by `${rowId}::${colKey}`. Written
  // on blur/Enter, reverted on Escape. The `editing` cursor tracks the
  // currently-open cell (only one at a time).
  const [edits, setEdits] = React.useState<Record<string, unknown>>({});
  const [editing, setEditing] = React.useState<string | null>(null);
  const editableSet = React.useMemo(
    () => new Set((props.editableColumns ?? []).filter((c): c is string => typeof c === "string")),
    [props.editableColumns],
  );
  const editableEnabled = editableSet.size > 0;
  const dirtyRowIds = React.useMemo(() => {
    const s = new Set<string>();
    for (const k of Object.keys(edits)) {
      const [rid] = k.split("::");
      if (rid) s.add(rid);
    }
    return s;
  }, [edits]);
  // In-flight tracking for row-action workflow dispatches, keyed per (row id +
  // action) so a slow dispatch on one row/action disables ONLY that button —
  // other rows and other actions stay clickable. Prevents double-dispatch from
  // a double-click while a workflow is running.
  const [busyKeys, setBusyKeys] = React.useState<Set<string>>(new Set());

  const ctxDispatch = useContext(WorkflowDispatcherContext);

  const formats = React.useMemo(() => {
    const m: Record<string, NonNullable<ColumnDef["format"]>> = {};
    const sample = (records ?? []).slice(0, 30);
    for (const c of columns) m[c.key] = inferFormat(c, sample.map((r) => r?.[c.key]));
    return m;
  }, [columns, records]);

  const filtered = React.useMemo(() => {
    if (!records) return [];
    const q = query.trim().toLowerCase();
    if (!q) return records;
    return records.filter((r) => columns.some((c) => String(r?.[c.key] ?? "").toLowerCase().includes(q)));
  }, [records, query, columns]);

  const sorted = React.useMemo(() => {
    if (!sortKey) return filtered;
    const arr = [...filtered];
    arr.sort((a, b) => {
      const av = a?.[sortKey], bv = b?.[sortKey];
      if (av == null) return 1;
      if (bv == null) return -1;
      const an = Number(av), bn = Number(bv);
      const cmp = !isNaN(an) && !isNaN(bn) ? an - bn : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const pageSize = props.pageSize && props.pageSize > 0 ? props.pageSize : 25;
  const paged = props.pageSize === 0 ? sorted : sorted.slice(page * pageSize, page * pageSize + pageSize);
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  React.useEffect(() => { setPage(0); }, [query, sortKey, sortDir]);

  function toggleSort(key: string) {
    if (sortKey !== key) { setSortKey(key); setSortDir("asc"); }
    else if (sortDir === "asc") setSortDir("desc");
    else setSortKey(null);
  }
  const rowId = (r: Record<string, unknown>, i: number) => String(r?.id ?? i);
  function toggleRow(id: string) {
    setSelected((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  const allOnPageSelected = paged.length > 0 && paged.every((r, i) => selected.has(rowId(r, i)));
  function toggleAll() {
    setSelected((prev) => {
      const n = new Set(prev);
      if (allOnPageSelected) paged.forEach((r, i) => n.delete(rowId(r, i)));
      else paged.forEach((r, i) => n.add(rowId(r, i)));
      return n;
    });
  }

  // ── Inline-edit helpers (Spec E Wave 3) ────────────────────────────────
  const editKey = (rid: string, col: string) => `${rid}::${col}`;
  const commitEdit = (rid: string, col: string, next: unknown, original: unknown) => {
    setEdits((prev) => {
      const key = editKey(rid, col);
      const n = { ...prev };
      // Treat "same as original" as a revert so the dirty count stays honest.
      if (next === original || (next == null && original == null)) {
        delete n[key];
      } else {
        n[key] = next;
      }
      return n;
    });
    setEditing(null);
  };
  const cancelEdit = () => setEditing(null);
  async function saveAllEdits() {
    if (dirtyRowIds.size === 0) return;
    // Group edits by row.
    const byRow: Record<string, Record<string, unknown>> = {};
    for (const [k, v] of Object.entries(edits)) {
      const [rid, col] = k.split("::");
      if (!rid || !col) continue;
      (byRow[rid] ??= {})[col] = v;
    }
    // Emit a per-row DOM event so the runtime can dispatch its own
    // mutation. Keeps the Table decoupled from the API layer while
    // still giving callers a hook they can adapt.
    if (typeof window !== "undefined") {
      for (const [rid, patch] of Object.entries(byRow)) {
        window.dispatchEvent(
          new CustomEvent("forge:row:update", {
            detail: { id: rid, patch },
          }),
        );
      }
    }
    if (props.editSaveWorkflow) {
      const dispatch = props.__dispatch ?? ctxDispatch ?? fallbackDispatch;
      try {
        await dispatch(props.editSaveWorkflow, { rows: byRow });
      } catch {
        /* let the caller surface errors — Table just clears local dirty state
           on success below. */
      }
    }
    setEdits({});
  }

  async function runAction(a: RowActionDef, r: Record<string, unknown>, key: string) {
    if (a.navigate) { const url = applyTemplate(a.navigate, r); if (typeof window !== "undefined") window.location.assign(url); return; }
    if (a.workflow) {
      // Re-entrancy guard: ignore clicks while this row-action is mid-flight
      // (belt-and-suspenders with the button's disabled attr).
      if (busyKeys.has(key)) return;
      const dispatch = props.__dispatch ?? ctxDispatch ?? fallbackDispatch;
      setBusyKeys((prev) => { const n = new Set(prev); n.add(key); return n; });
      try {
        await dispatch(a.workflow, { id: r?.id });
      } finally {
        setBusyKeys((prev) => { const n = new Set(prev); n.delete(key); return n; });
      }
    }
  }

  const colCount = columns.length + (selectable ? 1 : 0) + (rowActions?.length ? 1 : 0);
  const headBg = stickyHeader ? "sticky top-0 z-10" : "";
  const radiusCls = RADIUS_SURFACE_CLASS[useRadiusScale()];

  // Loading skeleton — renders inside the same chrome (border/radius/title
  // bar/column headers) so the layout is fixed and content shift is zero
  // when data arrives. Root-cause fix for CLS (B-021.5): every data-bound
  // library component honours isLoading. Only fires when the caller
  // explicitly sets isLoading — omitted means "assume ready" (backwards-
  // compatible with all existing schemas).
  if (props.isLoading) {
    const rowCount = Math.max(1, props.skeletonRows ?? props.pageSize ?? 6);
    const colCount = Math.max(1, columns.length || 4);
    return (
      <div
        data-table=""
        data-loading="true"
        className={`overflow-hidden ${radiusCls} border border-border bg-card${className ? ` ${className}` : ""}`}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        {title && (
          <div className="border-b border-border px-4 py-3">
            <div className="h-4 w-40 animate-pulse rounded bg-muted" aria-hidden />
          </div>
        )}
        {/* Same containment as the loaded table — otherwise the card is
            one width while loading and another once rows arrive. */}
        <div className={SCROLL_X}>
          <table className="w-full" style={{ borderCollapse: "collapse" }}>
            <thead className="bg-muted/40">
              <tr className="border-b border-border">
                {Array.from({ length: colCount }).map((_, i) => (
                  <th key={i} className={`${pad} text-start`}>
                    <div className="h-3 w-24 animate-pulse rounded bg-muted" aria-hidden />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: rowCount }).map((_, r) => (
                <tr key={r} className="border-b border-border last:border-0">
                  {Array.from({ length: colCount }).map((_, c) => (
                    <td key={c} className={pad}>
                      <div
                        className="h-3 animate-pulse rounded bg-muted"
                        style={{ width: `${50 + ((r + c) % 5) * 8}%` }}
                        aria-hidden
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div
      data-table=""
      className={`overflow-hidden ${radiusCls} border border-border bg-card${className ? ` ${className}` : ""}`}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {editableEnabled && dirtyRowIds.size > 0 && (
        <div
          data-forge-table-edit-toolbar
          className="flex items-center justify-between gap-3 border-b border-border bg-primary/5 px-4 py-2"
        >
          <span className="text-sm text-foreground">
            {dirtyRowIds.size} row{dirtyRowIds.size === 1 ? "" : "s"} with unsaved changes
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => { setEdits({}); setEditing(null); }}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={saveAllEdits}
              data-forge-table-save-all
              className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
            >
              Save all
            </button>
          </div>
        </div>
      )}
      {(title || searchable || selected.size > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
            {selected.size > 0 && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                {selected.size} selected
              </span>
            )}
          </div>
          {searchable && (
            <div className="relative">
              <span className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-muted-foreground">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
              </span>
              <input
                type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…"
                className="h-8 w-48 rounded-md border border-input bg-background ps-8 pe-3 text-sm text-foreground outline-none transition focus:ring-2 focus:ring-ring"
              />
            </div>
          )}
        </div>
      )}

      <div className={SCROLL_X} style={scrollEdgeStyle()}>
        <table className="w-full" style={{ borderCollapse: "collapse" }}>
          {caption && <caption className="px-4 py-2 text-start text-sm text-muted-foreground">{caption}</caption>}
          <thead className={`bg-muted/40 ${headBg}`}>
            <tr className="border-b border-border">
              {selectable && (
                <th className={`${pad} w-10`}>
                  <input type="checkbox" checked={allOnPageSelected} onChange={toggleAll} aria-label="Select all" className="cursor-pointer" />
                </th>
              )}
              {columns.map((col) => {
                const sortable = dataMode && (col.sortable ?? true);
                const align = col.align ?? (formats[col.key] === "number" || formats[col.key] === "currency" ? "right" : "left");
                return (
                  <th
                    key={col.key} scope="col" style={{ width: col.width, textAlign: align }}
                    className={`${pad} whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide text-muted-foreground ${sortable ? "cursor-pointer select-none hover:text-foreground" : ""}`}
                    onClick={sortable ? () => toggleSort(col.key) : undefined}
                  >
                    <span className="inline-flex items-center">{ensureHumanLabel(col.label || col.key)}{sortable && <SortIcon dir={sortKey === col.key ? sortDir : null} />}</span>
                  </th>
                );
              })}
              {rowActions?.length ? <th className={`${pad} w-px text-end text-[11px] font-semibold uppercase tracking-wide text-muted-foreground`} /> : null}
            </tr>
          </thead>
          <tbody className={txt}>
            {!dataMode && children}
            {dataMode && paged.length === 0 && (
              // data-forge-empty marks this as a DELIBERATE empty state. The
              // render-truth probe uses it to tell "nothing to show, and we
              // said so" apart from "the widget silently drew nothing" —
              // without a machine-readable marker the two are identical in
              // the DOM, and the probe would have to guess from prose.
              <tr data-forge-empty="table">
                <td colSpan={colCount} className="px-4 py-14 text-center">
                  {/* FIX-4 empty state — a first-run dashboard shouldn't be a
                      dead end. Renders an inline illustrative circle + a
                      quieted headline + an optional description + an optional
                      CTA (navigate/workflow). Search-empty stays a plain line
                      because the search box already tells the user what to do. */}
                  {query ? (
                    <span className="text-sm text-muted-foreground">
                      No results for “{query}”.
                    </span>
                  ) : (
                    <div className="mx-auto flex max-w-sm flex-col items-center gap-2">
                      <span
                        aria-hidden
                        className="mb-1 inline-flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground"
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="3" y="4" width="18" height="16" rx="2" />
                          <path d="M3 10h18" /><path d="M9 4v16" />
                        </svg>
                      </span>
                      <h4 className="text-sm font-medium text-foreground">
                        {emptyText || (title ? `No ${title.toLowerCase()} yet` : "Nothing here yet")}
                      </h4>
                      {props.emptyDescription && (
                        <p className="text-xs text-muted-foreground">
                          {props.emptyDescription}
                        </p>
                      )}
                      {props.emptyAction && (
                        <button
                          type="button"
                          onClick={async (e) => {
                            e.preventDefault();
                            const a = props.emptyAction!;
                            if (a.navigate) {
                              nav.push(a.navigate);
                              return;
                            }
                            if (a.workflow) {
                              const dispatch = props.__dispatch ?? ctxDispatch ?? fallbackDispatch;
                              try { await dispatch(a.workflow, {}); } catch { /* noop */ }
                            }
                          }}
                          className="mt-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:opacity-90"
                        >
                          {props.emptyAction.label}
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            )}
            {dataMode && paged.map((r, i) => {
              const id = rowId(r, i);
              const href = rowHref ? applyTemplate(rowHref, r) : undefined;
              const navAttrs = href ? { role: "link", tabIndex: 0, onClick: () => nav.push(href) } : {};
              return (
                <tr
                  key={id} {...(navAttrs as any)}
                  className={`border-b border-border/70 last:border-0 transition-colors hover:bg-muted/40 ${striped ? "even:bg-muted/20" : ""} ${selected.has(id) ? "bg-primary/5" : ""} ${href ? "cursor-pointer" : ""}`}
                >
                  {selectable && (
                    <td className={pad} onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={selected.has(id)} onChange={() => toggleRow(id)} aria-label={`Select row ${i + 1}`} className="cursor-pointer" />
                    </td>
                  )}
                  {columns.map((col) => {
                    const align = col.align ?? (formats[col.key] === "number" || formats[col.key] === "currency" ? "right" : "left");
                    const canEdit = editableSet.has(col.key);
                    const cellKey = editKey(id, col.key);
                    const original = r?.[col.key];
                    const patched = cellKey in edits ? edits[cellKey] : original;
                    const isDirty = cellKey in edits;
                    const isEditing = editing === cellKey;
                    return (
                      <td
                        key={col.key}
                        style={{ textAlign: align }}
                        className={`${pad} align-middle text-foreground ${canEdit ? "cursor-text" : ""} ${isDirty ? "bg-primary/5" : ""}`}
                        onClick={canEdit ? (e) => { e.stopPropagation(); setEditing(cellKey); } : undefined}
                      >
                        {canEdit && isEditing ? (
                          <EditableCell
                            initial={patched}
                            format={formats[col.key]}
                            onCancel={cancelEdit}
                            onCommit={(v) => commitEdit(id, col.key, v, original)}
                          />
                        ) : formats[col.key] === "sensitive" ? (
                          // Slice-4: sensitive cells need per-row context
                          // (the row id + the endpoint) that plain <Cell>
                          // does not thread through — render directly.
                          <SensitiveCell value={patched} col={col} rowId={id} />
                        ) : (
                          <Cell value={patched} fmt={formats[col.key]} />
                        )}
                      </td>
                    );
                  })}
                  {rowActions?.length ? (
                    <td className={`${pad} text-end`} onClick={(e) => e.stopPropagation()}>
                      <div className="flex justify-end gap-1">
                        {rowActions.map((a) => {
                          const actionKey = `${id}::${a.label}`;
                          const busy = busyKeys.has(actionKey);
                          return (
                            <button
                              key={a.label} type="button" onClick={() => runAction(a, r, actionKey)}
                              disabled={busy} aria-busy={busy ? "true" : undefined}
                              className={`rounded-md px-2 py-1 text-xs font-medium transition ${a.variant === "danger" ? "text-destructive hover:bg-destructive/10" : "text-muted-foreground hover:bg-muted hover:text-foreground"} ${busy ? "cursor-wait opacity-50" : ""}`}
                            >
                              {busy ? "…" : a.label}
                            </button>
                          );
                        })}
                      </div>
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {dataMode && props.pageSize !== 0 && sorted.length > pageSize && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm text-muted-foreground">
          <span>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, sorted.length)} of {sorted.length}</span>
          <div className="flex gap-1">
            <button type="button" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
            <button type="button" disabled={page >= pageCount - 1} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
