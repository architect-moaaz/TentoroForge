"use client";

/** How well a fact is known, as a dot: observed, derived, inferred, unknown. */
import type { Standing } from "./types";

export const STANDING_LABEL: Record<Standing, string> = {
  observed: "observed", derived: "derived", inferred: "inferred", unknown: "unknown",
};
const COLOR: Record<Standing, string> = {
  observed: "bg-emerald-500", derived: "bg-sky-500", inferred: "bg-amber-500", unknown: "bg-zinc-400",
};

export function StandingDot({ standing, className = "" }: { standing: Standing; className?: string }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${COLOR[standing] ?? COLOR.unknown} ${className}`} title={STANDING_LABEL[standing]} />;
}

/** The standings of a card's lines, as counts. */
export function StandingCounts({ counts }: { counts: Partial<Record<Standing, number>> }) {
  const order: Standing[] = ["observed", "derived", "inferred", "unknown"];
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
      {order.filter((s) => (counts[s] ?? 0) > 0).map((s) => (
        <span key={s} className="inline-flex items-center gap-1"><StandingDot standing={s} />{counts[s]} {STANDING_LABEL[s]}</span>
      ))}
    </span>
  );
}
