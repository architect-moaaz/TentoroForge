// frontend/src/components/schema-editor/FidelityScoreBadge.tsx

export function FidelityScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="rounded-full border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
        unscored
      </span>
    );
  }

  const tone =
    score >= 8
      ? "bg-emerald-100 text-emerald-800"
      : score >= 6
        ? "bg-amber-100 text-amber-800"
        : "bg-rose-100 text-rose-800";

  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>
      {score.toFixed(1)}
    </span>
  );
}
