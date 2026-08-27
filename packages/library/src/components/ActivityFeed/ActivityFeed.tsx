import * as React from "react";
import { formatValue } from "../../utils/formatValue";
import { z } from "zod";
import type { ActivityFeedNode } from "@tentoroforge/schema";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";
import { SCROLL_X } from "../../style/scroll";
import { applyRowCap } from "../../style/rowCap";
import { normalizeEntry } from "./normalizeEntry";

type Props = z.infer<typeof ActivityFeedNode>["props"];

const CATEGORY_TONE: Record<string, string> = {
  create:  "bg-emerald-500/10 text-emerald-700 border-emerald-200",
  update:  "bg-blue-500/10 text-blue-700 border-blue-200",
  approve: "bg-emerald-500/10 text-emerald-700 border-emerald-200",
  reject:  "bg-rose-500/10 text-rose-700 border-rose-200",
  comment: "bg-violet-500/10 text-violet-700 border-violet-200",
  system:  "bg-muted text-muted-foreground border-border",
};

function formatRelative(iso: string): string {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  // Deterministic (ISO) — toLocaleDateString() differs server vs client and trips
  // React hydration ("20/01/2025" SSR vs "1/20/2025" client).
  return formatValue(date);
}

function getInitials(name?: string, fallback?: string): string {
  if (fallback) return fallback;
  const parts = String(name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts.length === 1
    ? parts[0].slice(0, 2).toUpperCase()
    : ((parts[0][0] ?? "") + (parts[parts.length - 1][0] ?? "")).toUpperCase() || "?";
}

function formatRelativeSafe(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  return formatRelative(iso);
}


export function ActivityFeed({ entries, title = "Activity", maxHeight, limit, fields }: Props) {
  const radiusScale = useRadiusScale();
  // Schema accepts entries as either an inline array OR a Mustache binding
  // string (e.g. "{{stats.recentActivity}}"). When the binding hasn't been
  // resolved at render time, entries arrives as a string — render an
  // unresolved-binding placeholder rather than crashing on entries.length.
  // `limit` is written by the dashboard composer when this feed shares a
  // grid row — see style/rowCap. Unbounded, it decides the row height.
  const list = applyRowCap(Array.isArray(entries) ? entries : [], limit);
  const isUnresolvedBinding = typeof entries === "string";
  return (
    <section data-activity-feed="" className={`${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card ${SCROLL_X}`}>
      <header className="border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      </header>
      <ol
        className="overflow-y-auto"
        style={{ maxHeight: maxHeight != null
          ? (typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight)
          : "480px" }}
      >
        {isUnresolvedBinding ? (
          <li className="px-3 py-8 text-center text-xs italic text-muted-foreground/70">
            Activity binding {entries as string} — no fixture data available
          </li>
        ) : list.length === 0 ? (
          <li className="px-3 py-8 text-center text-xs text-muted-foreground">No activity yet.</li>
        ) : list.map((raw, i) => {
          const e = normalizeEntry(raw, i, fields as never);
          const rel = formatRelativeSafe(e.timestamp);
          return (
          <li key={e.id} className="flex gap-3 border-b border-border last:border-b-0 px-3 py-2.5 hover:bg-muted/30">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-[11px] font-semibold">
              {e.avatarUrl
                ? <img src={e.avatarUrl} alt={e.actorName} className="h-full w-full rounded-full object-cover" />
                : <span>{getInitials(e.actorName, e.avatarInitials)}</span>}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-tight">
                <span className="font-medium">{e.actorName}</span>
                {e.action && <span className="text-muted-foreground"> {e.action} </span>}
                {e.target && <span className="font-medium">{e.target}</span>}
              </p>
              {e.detail && <p className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2">{e.detail}</p>}
              <div className="mt-1 flex items-center gap-2">
                {rel && <span className="text-[10px] text-muted-foreground/70">{rel}</span>}
                {e.category && (
                  <span className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wide ${CATEGORY_TONE[e.category] ?? CATEGORY_TONE.system}`}>
                    {e.category}
                  </span>
                )}
              </div>
            </div>
          </li>
          );
        })}
      </ol>
    </section>
  );
}
