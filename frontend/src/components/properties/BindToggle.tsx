"use client";

export function BindToggle({
  isBound, onToggle,
}: { isBound: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`text-xs px-1.5 py-0.5 rounded ${
        isBound ? "bg-blue-500 text-white" : "border bg-muted/40 hover:bg-muted"
      }`}
      title={isBound ? "Bound — click to unbind to a literal value" : "Literal — click to bind"}
    >
      {isBound ? "{ }" : "Aa"}
    </button>
  );
}
