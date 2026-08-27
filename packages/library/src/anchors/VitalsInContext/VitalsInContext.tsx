"use client";
import * as React from "react";
import { z } from "zod";
import { useSurfaceClasses, skeleton } from "../anchor-shared";

/**
 * VitalsInContext — three tiles showing progress/count/streak, but each with
 * a contextual sub-line that turns raw numbers into meaning. Not a Stat card
 * strip — every tile has a "3 more to your goal" or "renews Sep 24" that
 * makes the number matter.
 */
export const VitalsInContextProps = z.object({
  tiles: z.array(z.object({
    label: z.string(),
    value: z.union([z.string(), z.number()]),
    unit: z.string().optional(),
    context: z.string().optional(),
    accent: z.enum(["primary", "success", "warning", "muted"]).optional(),
  })).min(1).max(4).optional(),
});
export type VitalsInContextPropsType = z.infer<typeof VitalsInContextProps>;

const ACCENT_COLOR: Record<string, string> = {
  primary: "var(--color-primary)",
  success: "var(--color-success-500, #16a34a)",
  warning: "var(--color-warning-500, #b27e24)",
  muted: "var(--color-text-secondary)",
};

export function VitalsInContext({ tiles }: VitalsInContextPropsType) {
  const items = tiles && tiles.length > 0 ? tiles : [{ label: "", value: "" }, { label: "", value: "" }, { label: "", value: "" }];
  const cols = items.length === 1 ? "grid-cols-1" : items.length === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3";
  return (
    <section
      data-anchor="vitals_in_context"
      className={`grid ${cols} gap-4`}
    >
      {items.map((t, i) => (
        <VitalTile key={i} tile={t} />
      ))}
    </section>
  );
}

function VitalTile({ tile }: { tile: NonNullable<VitalsInContextPropsType["tiles"]>[number] }) {
  const surface = useSurfaceClasses();
  const accentColor = tile.accent ? ACCENT_COLOR[tile.accent] : undefined;
  return (
    <div className={`${surface} flex flex-col gap-1`}>
      <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        {tile.label || <span className={skeleton("w-20")} />}
      </span>
      <div className="flex items-baseline gap-1.5">
        <span
          className="font-semibold tracking-tight text-foreground leading-none tabular-nums"
          style={{
            fontFamily: "var(--typography-font-heading, inherit)",
            fontSize: "clamp(1.75rem, 3vw, 2.25rem)",
            color: accentColor,
          }}
        >
          {String(tile.value) || <span className={skeleton("w-12")} />}
        </span>
        {tile.unit && <span className="text-sm text-muted-foreground font-medium">{tile.unit}</span>}
      </div>
      {tile.context && <span className="text-xs text-muted-foreground leading-relaxed">{tile.context}</span>}
    </div>
  );
}
