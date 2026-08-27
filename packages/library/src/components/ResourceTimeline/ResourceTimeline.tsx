"use client";

import React, { useMemo } from "react";
import type { ResourceTimelinePropsType } from "./ResourceTimeline.schema";

/** Categorical status → HSL bar colour. Falls back to a hashed hue. */
const STATUS_HUE: Record<string, number> = {
  confirmed: 221, arriving: 221, booked: 221, pending: 221, reserved: 221,
  inhouse: 152, "in-house": 152, active: 152, checkedin: 152, "checked-in": 152, occupied: 152,
  due: 38, dueout: 38, "due-out": 38, departing: 38, warning: 38,
  checkedout: 215, "checked-out": 215, done: 215, complete: 215, completed: 215, cancelled: 0,
  hold: 262, tentative: 262, blocked: 262,
};

function hueFor(status: string | undefined): number {
  if (!status) return 221;
  const key = String(status).toLowerCase().replace(/\s+/g, "");
  if (key in STATUS_HUE) return STATUS_HUE[key];
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 360;
  return h;
}

function isHold(status: string | undefined): boolean {
  const k = String(status || "").toLowerCase();
  return k.includes("hold") || k.includes("tentative") || k.includes("block");
}

function asArray(v: unknown): any[] {
  if (Array.isArray(v)) return v;
  if (v && typeof v === "object") return Object.values(v as object);
  return [];
}

function firstField(rec: any, candidates: string[], explicit?: string): string {
  if (explicit && rec && explicit in rec) return explicit;
  for (const c of candidates) if (rec && c in rec) return c;
  return explicit || candidates[0];
}

function parseDay(v: unknown): number | null {
  if (!v) return null;
  const s = String(v).slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) {
    const d = new Date(String(v));
    return isNaN(+d) ? null : Math.floor(d.getTime() / 86400000);
  }
  return Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3]) / 86400000);
}

function todayEpochDay(): number {
  const n = new Date();
  return Math.floor(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) / 86400000);
}

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function ResourceTimeline(props: ResourceTimelinePropsType & Record<string, any>) {
  const {
    resources, resourceIdField, resourceLabelField, resourceSubField, resourceGroupField,
    items, itemResourceField, startField, endField, titleField, subtitleField, statusField,
    itemHref, rangeStart, days = 14, emptyText = "No resources to display", className, style,
  } = props;

  const model = useMemo(() => {
    const resList = asArray(resources);
    const itemList = asArray(items);
    const startEpoch = parseDay(rangeStart) ?? todayEpochDay();
    const nDays = Math.max(1, Math.min(90, days || 14));
    const today = todayEpochDay();

    const sample = resList[0] || {};
    const idF = firstField(sample, ["id", "roomId", "key"], resourceIdField);
    const labelF = firstField(sample, ["name", "label", "title", "roomNumber", "number"], resourceLabelField);
    const subF = resourceSubField;
    const groupF = resourceGroupField;

    const iSample = itemList[0] || {};
    const resF = firstField(iSample, ["resourceId", "roomId", "resource"], itemResourceField);
    const startF = firstField(iSample, ["start", "startDate", "checkIn", "checkInDate", "from"], startField);
    const endF = firstField(iSample, ["end", "endDate", "checkOut", "checkOutDate", "to"], endField);
    const titleF = firstField(iSample, ["title", "name", "guestName", "label"], titleField);

    const byResource = new Map<string, any[]>();
    for (const it of itemList) {
      const rid = String(it?.[resF] ?? "");
      if (!byResource.has(rid)) byResource.set(rid, []);
      byResource.get(rid)!.push(it);
    }

    // Group resources (stable order of first appearance).
    const groups: { key: string; rows: any[] }[] = [];
    const gi = new Map<string, number>();
    for (const r of resList) {
      const g = groupF ? String(r?.[groupF] ?? "") : "";
      if (!gi.has(g)) { gi.set(g, groups.length); groups.push({ key: g, rows: [] }); }
      groups[gi.get(g)!].rows.push(r);
    }

    const columns = Array.from({ length: nDays }, (_, i) => {
      const epoch = startEpoch + i;
      const d = new Date(epoch * 86400000);
      return { epoch, dow: d.getUTCDay(), day: d.getUTCDate(), isToday: epoch === today };
    });

    return { groups, columns, byResource, startEpoch, nDays, idF, labelF, subF, groupF, resF, startF, endF, titleF };
  }, [resources, items, rangeStart, days, resourceIdField, resourceLabelField, resourceSubField,
      resourceGroupField, itemResourceField, startField, endField, titleField]);

  const { groups, columns, byResource, startEpoch, nDays, idF, labelF, subF, resF, startF, endF, titleF } = model;

  if (groups.length === 0) {
    return (
      <div className={className} style={style} data-timeline-empty>
        <div style={{ padding: "48px 16px", textAlign: "center", color: "hsl(var(--muted-foreground))" }}>
          {emptyText}
        </div>
      </div>
    );
  }

  const LABEL_W = 176;
  const gridCols = `${LABEL_W}px repeat(${nDays}, minmax(56px, 1fr))`;
  const statuses = Array.from(new Set(asArray(items).map((i) => statusField && i?.[statusField]).filter(Boolean))) as string[];

  return (
    <div
      className={className}
      data-resource-timeline
      style={{
        border: "1px solid hsl(var(--border))", borderRadius: "var(--radius, 0.5rem)",
        overflow: "auto", background: "hsl(var(--card))", fontSize: 13, ...style,
      }}
    >
      {/* Header */}
      <div style={{ display: "grid", gridTemplateColumns: gridCols, position: "sticky", top: 0, zIndex: 3, background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" }}>
        <div style={{ padding: "8px 12px", fontWeight: 600, color: "hsl(var(--muted-foreground))", textTransform: "uppercase", fontSize: 11, letterSpacing: ".04em", position: "sticky", left: 0, background: "hsl(var(--card))" }}>
          Resource
        </div>
        {columns.map((c, i) => (
          <div key={i} style={{ padding: "6px 4px", textAlign: "center", borderLeft: "1px solid hsl(var(--border))", background: c.isToday ? "hsl(var(--primary) / 0.08)" : undefined }}>
            <div style={{ fontSize: 10, textTransform: "uppercase", color: "hsl(var(--muted-foreground))" }}>{WD[c.dow]}</div>
            <div style={{ fontWeight: c.isToday ? 700 : 500, color: c.isToday ? "hsl(var(--primary))" : "hsl(var(--foreground))" }}>{c.day}</div>
          </div>
        ))}
      </div>

      {/* Body */}
      {groups.map((group, gIdx) => (
        <div key={gIdx} data-timeline-group>
          {model.groupF && (
            <div style={{ padding: "6px 12px", fontWeight: 700, fontSize: 11, letterSpacing: ".04em", textTransform: "uppercase", color: "hsl(var(--muted-foreground))", background: "hsl(var(--muted))", borderBottom: "1px solid hsl(var(--border))", position: "sticky", left: 0 }}>
              {group.key || "—"}
            </div>
          )}
          {group.rows.map((r, rIdx) => {
            const rid = String(r?.[idF] ?? "");
            const rowItems = byResource.get(rid) || [];
            return (
              <div key={rIdx} data-timeline-row style={{ display: "grid", gridTemplateColumns: gridCols, borderBottom: "1px solid hsl(var(--border))", minHeight: 44 }}>
                {/* label */}
                <div style={{ padding: "8px 12px", position: "sticky", left: 0, background: "hsl(var(--card))", zIndex: 2, borderRight: "1px solid hsl(var(--border))" }}>
                  <div style={{ fontWeight: 600, color: "hsl(var(--foreground))" }}>{String(r?.[labelF] ?? rid)}</div>
                  {subF && r?.[subF] != null && (
                    <div style={{ fontSize: 11, color: "hsl(var(--muted-foreground))" }}>{String(r[subF])}</div>
                  )}
                </div>
                {/* day background cells */}
                {columns.map((c, i) => (
                  <div key={i} style={{ gridColumn: `${i + 2} / ${i + 3}`, gridRow: 1, borderLeft: "1px solid hsl(var(--border) / 0.5)", background: c.isToday ? "hsl(var(--primary) / 0.05)" : c.dow === 0 || c.dow === 6 ? "hsl(var(--muted) / 0.5)" : undefined }} />
                ))}
                {/* item bars */}
                {rowItems.map((it, k) => {
                  const s = parseDay(it?.[startF]);
                  const e = parseDay(it?.[endF]) ?? (s != null ? s + 1 : null);
                  if (s == null || e == null) return null;
                  const from = Math.max(0, s - startEpoch);
                  const to = Math.min(nDays, e - startEpoch);
                  if (to <= 0 || from >= nDays || to <= from) return null;
                  const status = statusField ? it?.[statusField] : undefined;
                  const hue = hueFor(status);
                  const hold = isHold(status);
                  const label = String(it?.[titleF] ?? "");
                  const subtitle = subtitleField ? it?.[subtitleField] : undefined;
                  const bar = (
                    <div
                      title={`${label}${status ? " — " + status : ""}`}
                      style={{
                        gridColumn: `${from + 2} / ${to + 2}`, gridRow: 1, alignSelf: "center",
                        margin: "3px 2px", padding: "3px 8px", borderRadius: 6, overflow: "hidden",
                        background: hold ? "transparent" : `hsl(${hue} 70% 96%)`,
                        border: hold ? `1px dashed hsl(${hue} 45% 60%)` : `1px solid hsl(${hue} 60% 82%)`,
                        borderLeft: hold ? undefined : `3px solid hsl(${hue} 55% 50%)`,
                        color: `hsl(${hue} 45% 30%)`, cursor: itemHref ? "pointer" : "default", zIndex: 1,
                      }}
                      data-timeline-item
                    >
                      <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</div>
                      {subtitle != null && <div style={{ fontSize: 11, opacity: 0.8, whiteSpace: "nowrap" }}>{String(subtitle)}</div>}
                    </div>
                  );
                  const href = itemHref ? itemHref.replace(/\{(\w+)\}/g, (_m, f) => String(it?.[f] ?? "")) : null;
                  return href
                    ? <a key={k} href={href} style={{ display: "contents", textDecoration: "none" }}>{bar}</a>
                    : <React.Fragment key={k}>{bar}</React.Fragment>;
                })}
              </div>
            );
          })}
        </div>
      ))}

      {/* Status legend */}
      {statuses.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, padding: "8px 12px", borderTop: "1px solid hsl(var(--border))", position: "sticky", left: 0 }} data-timeline-legend>
          {statuses.map((s) => (
            <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "hsl(var(--muted-foreground))" }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, background: isHold(s) ? "transparent" : `hsl(${hueFor(s)} 70% 92%)`, border: isHold(s) ? `1px dashed hsl(${hueFor(s)} 45% 60%)` : `1px solid hsl(${hueFor(s)} 55% 50%)` }} />
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default ResourceTimeline;
