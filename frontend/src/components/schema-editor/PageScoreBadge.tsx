// frontend/src/components/schema-editor/PageScoreBadge.tsx
"use client";

interface PageScoreBadgeProps {
  score: number | null;
  failedFidelity?: boolean;
  exitStatus?: string;
  size?: "sm" | "md";
}

export function PageScoreBadge({
  score,
  failedFidelity,
  exitStatus,
  size = "sm",
}: PageScoreBadgeProps) {
  if (exitStatus === "budget") {
    return (
      <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground">
        skip
      </span>
    );
  }
  if (score === null || score === undefined) {
    return (
      <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground">
        —
      </span>
    );
  }
  const tone = failedFidelity
    ? "bg-amber-100 text-amber-800"
    : score >= 8
      ? "bg-emerald-100 text-emerald-800"
      : score >= 6
        ? "bg-amber-100 text-amber-800"
        : "bg-rose-100 text-rose-800";
  const cls =
    size === "sm"
      ? "rounded px-1.5 py-0.5 text-[10px] font-semibold"
      : "rounded-full px-2 py-0.5 text-[11px] font-semibold";
  return <span className={`${cls} ${tone}`}>{score.toFixed(1)}</span>;
}
