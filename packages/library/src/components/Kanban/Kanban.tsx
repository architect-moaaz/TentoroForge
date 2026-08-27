"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { KanbanPropsType } from "./Kanban.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Data-driven Kanban board.
 *
 * Two ways to feed it:
 *   1. Data mode (preferred): `data="{{tasks}}"` + `groupBy="status"`. The
 *      renderer interpolates `data` to an array of records; cards are grouped
 *      into columns by the `groupBy` field. Columns come from `columnOrder`
 *      (e.g. the status enum) or, failing that, the distinct values found.
 *   2. Static mode (legacy): a pre-shaped `columns` array.
 *
 * Cards support drag-and-drop between columns (with ‹ › click fallbacks). A
 * move fires `onCardMove(id, fromCol, toCol)` so the page can persist the new
 * status via an update workflow. Colours derive from the column key so a board
 * is legible without configuration, and everything is painted from design
 * tokens so it matches the generated app's theme.
 */

type RichCard = {
  id: string;
  title: string;
  description?: string;
  badge?: string;
  fields?: { label: string; value: string }[];
  href?: string;
};
type RichColumn = { id: string; title: string; color: string; cards: RichCard[] };

export interface KanbanProps extends KanbanPropsType {
  style?: StyleSlotT;
  onCardMove?: (cardId: string, fromCol: string, toCol: string) => void;
}

// A calm, legible palette keyed by column index, with sensible overrides for
// the status/priority vocabularies that show up in almost every app.
const PALETTE = ["#64748B", "#3B82F6", "#8B5CF6", "#F59E0B", "#10B981", "#EF4444", "#14B8A6", "#EC4899"];
const NAMED: Record<string, string> = {
  todo: "#64748B", backlog: "#64748B", new: "#64748B", open: "#64748B", pending: "#94A3B8",
  inprogress: "#3B82F6", doing: "#3B82F6", active: "#3B82F6", started: "#3B82F6",
  review: "#8B5CF6", inreview: "#8B5CF6", testing: "#8B5CF6", qa: "#8B5CF6",
  blocked: "#EF4444", onhold: "#F59E0B", paused: "#F59E0B",
  done: "#10B981", complete: "#10B981", completed: "#10B981", closed: "#10B981", resolved: "#10B981", approved: "#10B981",
  low: "#10B981", medium: "#F59E0B", high: "#EF4444", urgent: "#DC2626", critical: "#DC2626",
};

const norm = (s: unknown) => String(s ?? "").trim().toLowerCase().replace(/[\s_-]+/g, "");
function colorForKey(key: string, index: number): string {
  return NAMED[norm(key)] ?? PALETTE[index % PALETTE.length];
}

function humanize(key: string): string {
  const s = String(key ?? "").replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  return s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : "—";
}

function asText(v: unknown): string {
  if (v === null || v === undefined || v === false) return "";
  if (v instanceof Date) return v.toLocaleDateString("en-US");
  if (typeof v === "object") { try { return JSON.stringify(v); } catch { return ""; } }
  return String(v);
}

function applyTemplate(tpl: string, rec: Record<string, unknown>): string {
  return tpl.replace(/\{(\w+)\}/g, (_m, k) => asText(rec[k]));
}

/** Build display columns from bound records + field mappings. */
function buildFromData(p: KanbanPropsType): RichColumn[] {
  const rows = Array.isArray(p.data) ? (p.data as Record<string, unknown>[]) : [];
  const groupBy = p.groupBy || "status";
  const titleKey = p.cardTitle || "title";
  const descKey = p.cardDescription;
  const badgeKey = p.cardBadge;
  const extra = p.cardFields || [];

  // Column keys: explicit order first, then any extra distinct values present.
  const seen = new Set<string>();
  const keys: string[] = [];
  for (const k of p.columnOrder || []) { if (!seen.has(k)) { seen.add(k); keys.push(k); } }
  for (const r of rows) {
    const k = asText(r[groupBy]) || "Unassigned";
    if (!seen.has(k)) { seen.add(k); keys.push(k); }
  }
  if (keys.length === 0) keys.push("Unassigned");

  const byKey: Record<string, RichCard[]> = {};
  keys.forEach((k) => (byKey[k] = []));
  rows.forEach((r, i) => {
    const k = asText(r[groupBy]) || "Unassigned";
    if (!byKey[k]) byKey[k] = [];
    const id = asText(r.id) || `row-${i}`;
    byKey[k].push({
      id,
      title: asText(r[titleKey]) || asText(r.name) || asText(r.id) || "Untitled",
      description: descKey ? asText(r[descKey]) : undefined,
      badge: badgeKey ? asText(r[badgeKey]) : undefined,
      fields: extra
        .map((f) => ({ label: f.label || humanize(f.field), value: asText(r[f.field]) }))
        .filter((f) => f.value),
      href: p.cardHref ? applyTemplate(p.cardHref, r) : undefined,
    });
  });

  return keys.map((k, i) => ({ id: k, title: humanize(k), color: colorForKey(k, i), cards: byKey[k] || [] }));
}

/** Normalise the legacy static `columns` prop into the rich shape. */
function buildFromColumns(p: KanbanPropsType): RichColumn[] {
  const cols = (p.columns || []) as { id: string; title: string; color?: string; cards?: RichCard[] }[];
  return cols.map((c, i) => ({
    id: c.id,
    title: c.title,
    color: c.color || colorForKey(c.id || c.title, i),
    cards: (c.cards || []).map((card) => ({ ...card })),
  }));
}

function initials(s: string): string {
  const parts = String(s || "").trim().split(/\s+/).slice(0, 2);
  return parts.map((w) => w.charAt(0).toUpperCase()).join("") || "•";
}

export function Kanban(props: KanbanProps) {
  const { className, style, onCardMove, emptyText } = props;
  const dataMode = Array.isArray(props.data) || !!props.groupBy;

  const computed = React.useMemo<RichColumn[]>(
    () => (dataMode ? buildFromData(props) : buildFromColumns(props)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.data, props.groupBy, props.columnOrder, props.columns, props.cardTitle, props.cardDescription, props.cardBadge, props.cardFields, props.cardHref],
  );

  const [columns, setColumns] = React.useState<RichColumn[]>(computed);
  React.useEffect(() => setColumns(computed), [computed]);
  const [dragId, setDragId] = React.useState<string | null>(null);
  const [overCol, setOverCol] = React.useState<string | null>(null);

  const moveTo = React.useCallback(
    (cardId: string, toIndex: number) => {
      setColumns((prev) => {
        const fromIndex = prev.findIndex((col) => col.cards.some((c) => c.id === cardId));
        if (fromIndex === -1 || toIndex < 0 || toIndex >= prev.length || toIndex === fromIndex) return prev;
        const card = prev[fromIndex].cards.find((c) => c.id === cardId)!;
        const next = prev.map((col, i) => {
          if (i === fromIndex) return { ...col, cards: col.cards.filter((c) => c.id !== cardId) };
          if (i === toIndex) return { ...col, cards: [...col.cards, card] };
          return col;
        });
        onCardMove?.(cardId, prev[fromIndex].id, prev[toIndex].id);
        return next;
      });
    },
    [onCardMove],
  );

  const moveDir = React.useCallback(
    (cardId: string, dir: "left" | "right") => {
      const from = columns.findIndex((col) => col.cards.some((c) => c.id === cardId));
      moveTo(cardId, dir === "right" ? from + 1 : from - 1);
    },
    [columns, moveTo],
  );

  const total = columns.reduce((n, c) => n + c.cards.length, 0);
  if (total === 0 && columns.length <= 1) {
    return (
      <div
        data-kanban=""
        className={`rounded-lg border border-dashed border-border bg-muted/20 p-10 text-center text-sm text-muted-foreground${className ? ` ${className}` : ""}`}
        style={resolveStyle(style)}
      >
        {emptyText || "No items to display yet."}
      </div>
    );
  }

  return (
    <div
      data-kanban=""
      className={`flex gap-4 overflow-x-auto pb-2${className ? ` ${className}` : ""}`}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {columns.map((col, colIndex) => (
        <section
          key={col.id}
          data-testid={`kanban-col-${col.id}`}
          onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverCol(col.id); } }}
          onDragLeave={() => setOverCol((c) => (c === col.id ? null : c))}
          onDrop={(e) => {
            e.preventDefault();
            if (dragId) moveTo(dragId, colIndex);
            setDragId(null);
            setOverCol(null);
          }}
          className={`flex w-72 shrink-0 flex-col rounded-lg border bg-muted/30 transition-colors ${
            overCol === col.id ? "border-primary/60 bg-primary/5" : "border-border"
          }`}
        >
          {/* Column header */}
          <header
            className="flex items-center justify-between gap-2 rounded-t-lg border-b border-border px-3 py-2.5"
            style={{ boxShadow: `inset 0 2px 0 0 ${col.color}` }}
          >
            <div className="flex min-w-0 items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: col.color }} aria-hidden />
              <span className="truncate text-sm font-semibold text-foreground">{col.title}</span>
            </div>
            <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {col.cards.length}
            </span>
          </header>

          {/* Cards */}
          <div className="flex flex-1 flex-col gap-2 p-2">
            {col.cards.length === 0 && (
              <p className="px-1 py-6 text-center text-xs text-muted-foreground/70">Drop items here</p>
            )}
            {col.cards.map((card) => {
              const Tag: any = card.href ? "a" : "div";
              return (
                <Tag
                  key={card.id}
                  {...(card.href ? { href: card.href, "data-nav-trigger": card.href } : {})}
                  data-testid={`kanban-card-${card.id}`}
                  draggable
                  onDragStart={() => setDragId(card.id)}
                  onDragEnd={() => { setDragId(null); setOverCol(null); }}
                  className={`group block cursor-grab rounded-md border border-border bg-card p-2.5 text-left shadow-sm transition hover:border-primary/40 hover:shadow active:cursor-grabbing ${
                    dragId === card.id ? "opacity-50" : ""
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium leading-snug text-card-foreground">{card.title}</span>
                    {card.badge && (
                      <span
                        className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                        style={{ background: `${colorForKey(card.badge, 0)}1A`, color: colorForKey(card.badge, 0) }}
                      >
                        {humanize(card.badge)}
                      </span>
                    )}
                  </div>

                  {card.description && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{card.description}</p>
                  )}

                  {card.fields && card.fields.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {card.fields.map((f) => {
                        const isPerson = /assign|owner|user|author|member|lead/i.test(f.label);
                        return isPerson ? (
                          <span key={f.label} className="flex items-center gap-1" title={`${f.label}: ${f.value}`}>
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary">
                              {initials(f.value)}
                            </span>
                            <span className="text-[11px] text-muted-foreground">{f.value}</span>
                          </span>
                        ) : (
                          <span
                            key={f.label}
                            className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
                            title={f.label}
                          >
                            {f.value}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Move controls — click fallback for drag-and-drop */}
                  <div className="mt-2 flex justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      type="button"
                      aria-label={`Move ${card.title} left`}
                      disabled={colIndex === 0}
                      onClick={(e) => { e.preventDefault(); moveDir(card.id, "left"); }}
                      className="rounded px-1 py-0.5 text-xs text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      ‹
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${card.title} right`}
                      disabled={colIndex === columns.length - 1}
                      onClick={(e) => { e.preventDefault(); moveDir(card.id, "right"); }}
                      className="rounded px-1 py-0.5 text-xs text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      ›
                    </button>
                  </div>
                </Tag>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
