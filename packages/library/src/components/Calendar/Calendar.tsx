"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CalendarPropsType } from "./Calendar.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useElevation, useRadiusScale } from "../../theme/tokens-context";

/**
 * Calendar with two modes:
 *
 *   1. Event mode (preferred for data views): `events="{{bookings}}"` +
 *      `dateField="checkIn"`. Records are plotted across Month / Week / Agenda
 *      views. Clicking an event opens an Outlook-style detail popover showing the
 *      record's fields, with an "Open" deep link (`eventHref`). Multi-day spans
 *      (`endDateField`), colour-by-category (`colorField`) and a day agenda are
 *      supported.
 *   2. Picker mode (legacy): `value` + `onChange` select a single day.
 *
 * Painted entirely from design tokens so it matches the generated app's theme.
 */

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const EVENT_PALETTE = ["#3B82F6", "#8B5CF6", "#10B981", "#F59E0B", "#EF4444", "#14B8A6", "#EC4899", "#6366F1"];
const SYSTEM = new Set(["id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"]);

export interface CalendarProps extends CalendarPropsType {
  style?: StyleSlotT;
  onChange?: (iso: string) => void;
}

type Ymd = { year: number; month: number; day: number };
type CalEvent = {
  id: string; title: string; start: Ymd; end: Ymd; color: string;
  href?: string; record: Record<string, unknown>;
};
type View = "month" | "week" | "agenda";

function asText(v: unknown): string {
  if (v === null || v === undefined || v === false) return "";
  if (v instanceof Date) return v.toISOString();
  return String(v);
}
function parseYmd(value: unknown): Ymd | null {
  if (value instanceof Date && !isNaN(value.getTime())) return { year: value.getFullYear(), month: value.getMonth(), day: value.getDate() };
  const m = asText(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  return { year: Number(m[1]), month: Number(m[2]) - 1, day: Number(m[3]) };
}
const sameYmd = (a: Ymd | null, y: number, m: number, d: number) => !!a && a.year === y && a.month === m && a.day === d;
const utc = (y: Ymd) => Date.UTC(y.year, y.month, y.day);
function applyTemplate(tpl: string, rec: Record<string, unknown>): string {
  return tpl.replace(/\{(\w+)\}/g, (_x, k) => asText(rec[k]));
}
function humanize(key: string): string {
  const s = String(key ?? "").replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  return s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : key;
}
function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const d = parseYmd(v);
  if (d && /^\d{4}-\d{2}-\d{2}/.test(asText(v))) return new Date(d.year, d.month, d.day).toLocaleDateString();
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch { return ""; } }
  return String(v);
}

/**
 * Token-elevation → shadow, copied from Card so a Calendar sitting next to a
 * Card on the same page reads as the same kind of surface. Before this the
 * Calendar was the only large surface in the library painting a bare 1px border
 * and no shadow at all, which is a large part of why it "looks terrible" beside
 * its neighbours.
 */
const TOKEN_ELEVATION_CLASSES: Record<"flat" | "bordered" | "layered" | "floating", string> = {
  flat:     "shadow-none",
  bordered: "border-2 shadow-none",
  layered:  "shadow-sm",
  floating: "shadow-lg",
};

/**
 * Month-cell height. Responsive rather than the old flat `min-h-[84px]`: seven
 * 84px columns inside a 375px device frame gave a 53px-wide cell whose event
 * chips could not show a single word.
 */
const DAY_CELL_MIN_H = "min-h-[64px] sm:min-h-[92px]";
/** See the month-grid comment — removes the doubled outer seams. */
const GRID_EDGE_TRIM =
  "[&>*:nth-child(7n)]:border-e-0 [&>*:nth-last-child(-n+7)]:border-b-0";

const colorCache = new Map<string, string>();
function colorForCategory(cat: string): string {
  if (!cat) return EVENT_PALETTE[0];
  const hit = colorCache.get(cat);
  if (hit) return hit;
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0;
  const c = EVENT_PALETTE[h % EVENT_PALETTE.length];
  colorCache.set(cat, c);
  return c;
}

function buildEvents(p: CalendarPropsType): CalEvent[] {
  const rows = Array.isArray(p.events) ? (p.events as Record<string, unknown>[]) : [];
  const dateKey = p.dateField || "date";
  const endKey = p.endDateField;
  const titleKey = p.titleField || "title";
  const colorKey = p.colorField;
  const out: CalEvent[] = [];
  rows.forEach((r, i) => {
    const start = parseYmd(r[dateKey]);
    if (!start) return;
    const end = (endKey && parseYmd(r[endKey])) || start;
    const cat = colorKey ? asText(r[colorKey]) : "";
    out.push({
      id: asText(r.id) || `ev-${i}`,
      title: asText(r[titleKey]) || asText(r.name) || asText(r.id) || "Untitled",
      start, end, color: colorForCategory(cat || (colorKey ? "" : "default")),
      href: p.eventHref ? applyTemplate(p.eventHref, r) : undefined,
      record: r,
    });
  });
  return out;
}
const coversDay = (ev: CalEvent, y: number, m: number, d: number) => {
  const t = Date.UTC(y, m, d), s = utc(ev.start), e = utc(ev.end);
  return t >= s && t <= (e >= s ? e : s);
};

export function Calendar(props: CalendarProps) {
  const { name, value, className, style, onChange, emptyText } = props;
  const radiusScale = useRadiusScale();
  const elevation = useElevation();
  const eventMode = Array.isArray(props.events);
  const events = React.useMemo(() => (eventMode ? buildEvents(props) : []), // eslint-disable-line react-hooks/exhaustive-deps
    [props.events, props.dateField, props.endDateField, props.titleField, props.colorField, props.eventHref]);

  const today = new Date();
  const tYmd: Ymd = { year: today.getFullYear(), month: today.getMonth(), day: today.getDate() };
  const parsed = parseYmd(value);
  const initial = parsed || events[0]?.start || tYmd;

  const [view, setView] = React.useState<View>((props.view as View) || "month");
  const [displayed, setDisplayed] = React.useState({ year: initial.year, month: initial.month });
  const [selected, setSelected] = React.useState<Ymd | null>(eventMode ? tYmd : parsed);
  const [active, setActive] = React.useState<{ ev: CalEvent; x: number; y: number } | null>(null);
  React.useEffect(() => {
    if (!parsed) return;
    setDisplayed({ year: parsed.year, month: parsed.month });
    // Re-seed the selection too, but ONLY in picker mode: that mode now paints
    // its highlight from `selected`, so a controlled `value` write has to move
    // it or the parent would be ignored. Event mode deliberately keeps its
    // selection on TODAY regardless of `value` — `value` only chooses the month
    // to open on there, and the day-agenda strip underneath is "today's events".
    if (!eventMode) setSelected(parsed);
  }, [value]); // eslint-disable-line
  React.useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setActive(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  const { year, month } = displayed;
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  function step(dir: number) {
    if (view === "week" && selected) {
      const d = new Date(selected.year, selected.month, selected.day + dir * 7);
      setSelected({ year: d.getFullYear(), month: d.getMonth(), day: d.getDate() });
      setDisplayed({ year: d.getFullYear(), month: d.getMonth() });
      return;
    }
    setDisplayed(({ year: y, month: m }) => {
      const nm = m + dir;
      if (nm < 0) return { year: y - 1, month: 11 };
      if (nm > 11) return { year: y + 1, month: 0 };
      return { year: y, month: nm };
    });
  }
  /**
   * "Today" — jump the displayed month to the current one AND select today.
   *
   * The reported failure ("what does this today do, it is not doing anything")
   * was real and total in picker mode, which is what a Calendar dropped from the
   * palette is: the grid already opens on the current month, so re-setting
   * `displayed` is a no-op, and the picker grid painted its selected ring from
   * the `value` PROP rather than from `selected` state — so the one thing this
   * function does change was not rendered anywhere. Fixed at the render site
   * (picker mode now reads `selected`), which also makes plain day clicks
   * highlight in an app that has no controlled parent writing `value` back.
   */
  function goToday() { setDisplayed({ year: tYmd.year, month: tYmd.month }); setSelected(tYmd); }
  function clickDay(day: number) {
    const ymd = { year, month, day };
    setSelected(ymd);
    if (onChange) onChange(`${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`);
  }
  function openEvent(e: React.MouseEvent, ev: CalEvent) {
    e.stopPropagation();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setActive({ ev, x: r.left, y: r.bottom });
  }

  const blanks = Array.from({ length: firstWeekday });
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);
  // Pad the last week out to seven. Without this the month grid simply STOPPED
  // mid-row — a month ending on a Tuesday left five cell-widths of nothing below
  // a ragged, un-bordered edge, inside a container that still drew its own
  // border around the gap. That torn bottom edge is the single most visible part
  // of "this calendar looks terrible".
  const trailing = Array.from({ length: (7 - ((firstWeekday + daysInMonth) % 7)) % 7 });
  const agenda = selected ? events.filter((ev) => coversDay(ev, selected.year, selected.month, selected.day)) : [];

  // Days for the week view (week containing `selected`, else the display month's first week).
  const weekDays = React.useMemo(() => {
    const base = selected ? new Date(selected.year, selected.month, selected.day) : new Date(year, month, 1);
    const sun = new Date(base); sun.setDate(base.getDate() - base.getDay());
    return Array.from({ length: 7 }, (_, i) => { const d = new Date(sun); d.setDate(sun.getDate() + i); return d; });
  }, [selected, year, month]);

  // Upcoming events for agenda view, grouped by day.
  const agendaGroups = React.useMemo(() => {
    const from = Date.UTC(year, month, 1);
    const list = events.filter((ev) => utc(ev.end) >= from).sort((a, b) => utc(a.start) - utc(b.start));
    const groups: { key: string; date: Date; items: CalEvent[] }[] = [];
    for (const ev of list) {
      const key = `${ev.start.year}-${ev.start.month}-${ev.start.day}`;
      let g = groups.find((x) => x.key === key);
      if (!g) { g = { key, date: new Date(ev.start.year, ev.start.month, ev.start.day), items: [] }; groups.push(g); }
      g.items.push(ev);
    }
    return groups;
  }, [events, year, month]);

  const chip = (ev: CalEvent, key: string) => (
    <span key={key} title={ev.title} onClick={(e) => openEvent(e, ev)}
      className="block cursor-pointer truncate rounded px-1 py-0.5 text-[11px] font-medium text-white hover:opacity-90"
      style={{ background: ev.color }}>
      {ev.title}
    </span>
  );

  const headerLabel = view === "week" && selected
    ? `Week of ${new Date(weekDays[0]).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
    : `${MONTH_NAMES[month]} ${year}`;

  return (
    <div
      data-calendar="" data-mode={eventMode ? "events" : "picker"} data-view={view}
      // `overflow-hidden` is load-bearing, not cosmetic: the day cells paint
      // their own backgrounds and hairlines right into all four corners, so
      // without a clip the rounded border was visibly squared off at the bottom
      // and the leading blank cells' grey block sat over the top-left curve.
      // Card carries the same class for the same reason.
      className={[
        "overflow-hidden border border-border bg-card text-card-foreground",
        RADIUS_SURFACE_CLASS[radiusScale],
        TOKEN_ELEVATION_CLASSES[elevation],
        className ?? "",
      ].filter(Boolean).join(" ")}
      style={resolveStyle(style)} {...useMotion(style?.motion)}
    >
      {/* `name` used to be destructured and thrown away, and the component
          renders no <input> of its own, so FormData never saw the picked date.
          Same hidden-input pattern as Switch.tsx. */}
      {name && (
        <input
          type="hidden"
          name={name}
          value={
            selected
              ? `${selected.year}-${String(selected.month + 1).padStart(2, "0")}-${String(selected.day).padStart(2, "0")}`
              : ""
          }
          readOnly
        />
      )}
      {/* Header — px-4 py-3 is the Card/Table header rhythm; the old px-3 py-2.5
        * made the one piece of chrome the user reads first look cramped next to
        * every other surface on the page. */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <span className="text-sm font-semibold text-foreground">{headerLabel}</span>
        <div className="flex items-center gap-2">
          {eventMode && (
            <div className="flex rounded-md border border-border p-0.5">
              {(["month", "week", "agenda"] as View[]).map((v) => (
                <button key={v} type="button" onClick={() => setView(v)}
                  className={`rounded px-2 py-0.5 text-xs font-medium capitalize transition ${view === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
                  {v}
                </button>
              ))}
            </div>
          )}
          <button type="button" onClick={goToday} className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted">Today</button>
          <button type="button" aria-label="Previous month" onClick={() => step(-1)} className="rounded-md p-1 text-muted-foreground hover:bg-muted">‹</button>
          <button type="button" aria-label="Next month" onClick={() => step(1)} className="rounded-md p-1 text-muted-foreground hover:bg-muted">›</button>
        </div>
      </div>

      {/* Weekday header (month/week grids) */}
      {(view === "month" || view === "week" || !eventMode) && (
        <div className="grid grid-cols-7 border-b border-border bg-muted/30">
          {WEEKDAY_LABELS.map((wd) => (
            <span key={wd} className="py-2 text-center text-xs font-medium uppercase tracking-wide text-muted-foreground">{wd}</span>
          ))}
        </div>
      )}

      {eventMode && view === "month" && (
        // Strip the hairline off the last column and the last row. Every cell
        // used to carry `border-b border-e` unconditionally, so the right-hand
        // column doubled up against the container's own border and the bottom
        // row doubled up against the day-agenda's `border-t` — two 2px seams
        // framing the grid. `nth-last-child(-n+7)` is only correct because the
        // month is now always padded to whole weeks (see `trailing`).
        <div className={`grid grid-cols-7 ${GRID_EDGE_TRIM}`}>
          {blanks.map((_, i) => <div key={`b-${i}`} className={`${DAY_CELL_MIN_H} border-b border-e border-border bg-muted/30`} />)}
          {days.map((day) => {
            const isToday = sameYmd(tYmd, year, month, day);
            const isSel = sameYmd(selected, year, month, day);
            const dayEvents = events.filter((ev) => coversDay(ev, year, month, day));
            return (
              <button key={day} type="button" onClick={() => clickDay(day)} data-testid={`cal-day-${day}`}
                className={`${DAY_CELL_MIN_H} border-b border-e border-border p-1.5 text-start align-top transition-colors hover:bg-muted/40 ${isSel ? "bg-primary/5 ring-1 ring-inset ring-primary/40" : ""}`}>
                <span className={`mb-1 inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-xs ${isToday ? "bg-primary font-semibold text-primary-foreground" : "text-foreground"}`}>{day}</span>
                <div className="space-y-0.5">
                  {dayEvents.slice(0, 3).map((ev, k) => chip(ev, `${ev.id}-${k}`))}
                  {dayEvents.length > 3 && <span className="block px-1 text-[10px] text-muted-foreground">+{dayEvents.length - 3} more</span>}
                </div>
              </button>
            );
          })}
          {trailing.map((_, i) => <div key={`t-${i}`} className={`${DAY_CELL_MIN_H} border-b border-e border-border bg-muted/30`} />)}
        </div>
      )}

      {eventMode && view === "week" && (
        <div className={`grid grid-cols-7 ${GRID_EDGE_TRIM}`}>
          {weekDays.map((d, i) => {
            const y = d.getFullYear(), m = d.getMonth(), dd = d.getDate();
            const isToday = sameYmd(tYmd, y, m, dd);
            const dayEvents = events.filter((ev) => coversDay(ev, y, m, dd));
            return (
              <button key={i} type="button" onClick={() => { setSelected({ year: y, month: m, day: dd }); setDisplayed({ year: y, month: m }); }}
                className={`min-h-[220px] border-b border-e border-border p-1.5 text-start align-top hover:bg-muted/40 ${sameYmd(selected, y, m, dd) ? "bg-primary/5" : ""}`}>
                <span className={`mb-1 inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-sm ${isToday ? "bg-primary font-semibold text-primary-foreground" : "text-foreground"}`}>{dd}</span>
                <div className="space-y-1">{dayEvents.map((ev, k) => chip(ev, `${ev.id}-${k}`))}</div>
              </button>
            );
          })}
        </div>
      )}

      {eventMode && view === "agenda" && (
        <div className="max-h-[420px] overflow-y-auto px-3 py-2">
          {agendaGroups.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">{emptyText || "No upcoming events."}</p>}
          {agendaGroups.map((g) => (
            <div key={g.key} className="mb-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {g.date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
              </p>
              <ul className="space-y-1">
                {g.items.map((ev, k) => (
                  <li key={`${ev.id}-${k}`} onClick={(e) => openEvent(e as any, ev)}
                    className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-sm hover:bg-muted/40">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: ev.color }} />
                    <span className="truncate text-card-foreground">{ev.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {/* Picker grid (legacy) */}
      {!eventMode && (
        <div className="grid grid-cols-7 gap-1 p-3">
          {blanks.map((_, i) => <span key={`b-${i}`} />)}
          {days.map((day) => {
            // `selected`, not `parsed`. The old code painted the highlight from
            // the `value` PROP, so in the uncontrolled case that a dropped
            // Calendar (and most generated apps) actually is, neither clicking a
            // day nor pressing Today moved anything — the reported "what does
            // this today do, it is not doing anything". `selected` is seeded
            // from `value` and re-seeded whenever `value` changes, so a truly
            // controlled parent behaves exactly as before.
            const isSel = sameYmd(selected, year, month, day);
            const isToday = sameYmd(tYmd, year, month, day);
            return (
              <button key={day} type="button" onClick={() => clickDay(day)} data-testid={`cal-day-${day}`}
                aria-pressed={isSel}
                className={`mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isSel ? "bg-primary font-semibold text-primary-foreground" : isToday ? "font-semibold text-primary ring-1 ring-inset ring-primary/40 hover:bg-muted" : "text-foreground hover:bg-muted"}`}>
                {day}
              </button>
            );
          })}
        </div>
      )}

      {/* Day agenda (month view) */}
      {eventMode && view === "month" && selected && (
        <div className="border-t border-border px-3 py-2.5">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {MONTH_NAMES[selected.month]} {selected.day}, {selected.year}
          </p>
          {agenda.length === 0 ? (
            <p className="py-2 text-xs text-muted-foreground/70">{emptyText || "No events this day."}</p>
          ) : (
            <ul className="space-y-1">
              {agenda.map((ev, k) => (
                <li key={`${ev.id}-${k}`} onClick={(e) => openEvent(e as any, ev)}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: ev.color }} />
                  <span className="truncate text-card-foreground">{ev.title}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Outlook-style event detail popover */}
      {active && (
        <EventPopover
          active={active}
          detailFields={props.detailFields}
          hiddenKeys={new Set([props.dateField || "date", props.endDateField || "", props.titleField || "title", props.colorField || "", "id"].filter(Boolean).map((s) => s.toLowerCase()))}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}

function EventPopover({
  active, detailFields, hiddenKeys, onClose,
}: {
  active: { ev: CalEvent; x: number; y: number };
  detailFields?: string[];
  hiddenKeys: Set<string>;
  onClose: () => void;
}) {
  const { ev, x, y } = active;
  const W = 300;
  const left = typeof window !== "undefined" ? Math.min(Math.max(8, x), window.innerWidth - W - 8) : x;
  const top = typeof window !== "undefined" ? Math.min(y + 6, window.innerHeight - 260) : y + 6;

  const rec = ev.record || {};
  const keys = detailFields && detailFields.length
    ? detailFields
    : Object.keys(rec).filter((k) => !hiddenKeys.has(k.toLowerCase()) && !SYSTEM.has(k.toLowerCase()) && !/(_id|Id)$/.test(k));
  const rangeSame = utc(ev.start) === utc(ev.end);
  const fmtYmd = (d: typeof ev.start) => new Date(d.year, d.month, d.day).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        role="dialog" data-event-popover=""
        className="fixed z-50 w-[300px] overflow-hidden rounded-lg border border-border bg-card shadow-lg"
        style={{ left, top }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="h-1.5 w-full" style={{ background: ev.color }} />
        <div className="p-3.5">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold leading-snug text-foreground">{ev.title}</h3>
            <button type="button" aria-label="Close" onClick={onClose} className="-me-1 -mt-1 rounded p-1 text-muted-foreground hover:bg-muted">✕</button>
          </div>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: ev.color }} />
            {rangeSame ? fmtYmd(ev.start) : `${fmtYmd(ev.start)} → ${fmtYmd(ev.end)}`}
          </p>

          {keys.length > 0 && (
            <dl className="mt-3 space-y-1.5 border-t border-border pt-3">
              {keys.slice(0, 8).map((k) => (
                <div key={k} className="flex items-start justify-between gap-3 text-xs">
                  <dt className="shrink-0 text-muted-foreground">{humanize(k)}</dt>
                  <dd className="text-end text-card-foreground">{fmtValue(rec[k])}</dd>
                </div>
              ))}
            </dl>
          )}

          {ev.href && (
            <a href={ev.href} data-nav-trigger={ev.href}
              className="mt-3 flex w-full items-center justify-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90">
              Open details
            </a>
          )}
        </div>
      </div>
    </>
  );
}
