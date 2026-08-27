"use client";

import { HelpCircle } from "lucide-react";

// Smith Auto-Act (S4) — the picker Smith shows when resolve_target
// returns kind="chip" (2-4 candidates, none confident). Each candidate
// becomes a button that fires the *original* ask scoped to that route.
// "Apply to all" fires the ask with an "everywhere" hint so
// resolve_target routes it as act_all next turn.

export interface DisambiguationCandidate {
  route: string;
  label?: string;
  excerpt?: string;
}

export interface DisambiguationPayload {
  query: string;
  candidates: DisambiguationCandidate[];
  reason?: string;
}

interface Props {
  payload: DisambiguationPayload;
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function DisambiguationCard({ payload, onSend, disabled }: Props) {
  const { query, candidates } = payload;
  if (!candidates.length) return null;

  const pickOne = (c: DisambiguationCandidate) => {
    onSend(`${query} — on ${c.route}${c.label ? ` (${c.label})` : ""}`);
  };
  const pickAll = () => {
    onSend(`${query} — everywhere`);
  };

  return (
    <div className="mt-3 rounded-lg border border-border bg-background p-3 text-[13px]">
      <div className="flex items-center gap-2 text-muted-foreground">
        <HelpCircle className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">Which one?</span>
      </div>
      <div className="mt-2 flex flex-col gap-1.5">
        {candidates.slice(0, 4).map((c) => (
          <button
            key={c.route + c.label}
            type="button"
            disabled={disabled}
            onClick={() => pickOne(c)}
            className="flex flex-col items-start gap-0.5 rounded-md border border-border bg-background px-3 py-2 text-left transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="text-[13px] font-medium">{c.route}</span>
            {c.excerpt && (
              <span className="text-[11px] text-muted-foreground line-clamp-1">
                {c.excerpt}
              </span>
            )}
          </button>
        ))}
      </div>
      {candidates.length > 1 && (
        <button
          type="button"
          disabled={disabled}
          onClick={pickAll}
          className="mt-2 inline-flex w-full items-center justify-center rounded-md border border-dashed border-border px-3 py-1.5 text-[11px] font-medium text-muted-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          Apply to all {candidates.length} pages
        </button>
      )}
    </div>
  );
}
