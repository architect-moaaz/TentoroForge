"use client";
import * as React from "react";
import { z } from "zod";

/**
 * EmergencyActionRail — a permanent bar of dangerous, one-tap ops actions
 * (page on-call, freeze intake, escalate to L3). Not "primary CTA" style —
 * these are red-outline buttons that need thought before use, but must
 * always be reachable.
 */
export const EmergencyActionRailProps = z.object({
  title: z.string().optional(),
  actions: z.array(z.object({
    label: z.string(),
    detail: z.string().optional(),
    severity: z.enum(["danger", "warning"]).optional(),
    icon: z.string().optional(),         // single glyph
    navigate: z.string().optional(),
    confirm: z.boolean().optional(),
  })).min(1).max(4).optional(),
});
export type EmergencyActionRailPropsType = z.infer<typeof EmergencyActionRailProps>;

const SEV: Record<string, string> = {
  danger:  "border-red-500/60 text-red-700 hover:bg-red-500/10",
  warning: "border-yellow-500/60 text-yellow-700 hover:bg-yellow-500/10",
};

export function EmergencyActionRail({ title, actions }: EmergencyActionRailPropsType) {
  const items = actions && actions.length > 0 ? actions : [];
  if (items.length === 0) return null;
  return (
    <section
      data-anchor="emergency_action_rail"
      className="rounded-xl border-2 border-dashed border-red-500/30 bg-red-500/5 px-5 py-4"
    >
      <header className="flex items-baseline justify-between mb-3">
        <h3
          className="text-xs font-bold uppercase tracking-widest text-red-700 flex items-center gap-2"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          <span aria-hidden="true">⚠</span>
          {title || "Emergency"}
        </h3>
      </header>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2">
        {items.map((a, i) => (
          <a
            key={i}
            href={a.navigate || "#"}
            onClick={(e) => { if (a.confirm && !confirm(`${a.label} — are you sure?`)) e.preventDefault(); }}
            className={`flex flex-col items-start gap-1 rounded-lg border-2 bg-background px-4 py-3 text-left transition ${SEV[a.severity || "danger"]}`}
          >
            <span className="flex items-center gap-2 font-semibold text-sm">
              {a.icon && <span aria-hidden="true">{a.icon}</span>}
              {a.label}
            </span>
            {a.detail && <span className="text-[11px] opacity-80">{a.detail}</span>}
          </a>
        ))}
      </div>
    </section>
  );
}
