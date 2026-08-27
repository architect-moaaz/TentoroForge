"use client";

/**
 * NeedsUserCard — renders architect's request for a user decision.
 *
 * Backend contract (from services/smith_session.py `TurnResult`):
 *   status: "needs_user"
 *   answer: architect-voice question (already in Smith's persona)
 *   options: string[]     // each is a phrase the user can click
 *
 * Each option becomes a button; clicking posts the exact string
 * back to /chat as the next user message. This is the correct
 * shape for the S7 iteration flow's failure semantics (§11 of the
 * Smith-as-architect spec) — no silent rollback, no canned template,
 * the user picks what happens next.
 */
import { AlertTriangle, ChevronRight } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export interface NeedsUserPayload {
  /** The architect's question to the user. Rendered as markdown. */
  answer: string;
  /** Concrete choices — retry / rollback / abandon / etc. */
  options: string[];
  /** Optional git diff summary of what was attempted before the ask. */
  diff_summary?: string;
  /** Optional paths that were touched. */
  touched_paths?: string[];
}

interface NeedsUserCardProps {
  payload: NeedsUserPayload;
  /** Posts the selected option string back as the next chat message. */
  onSelect: (choice: string) => void;
  disabled?: boolean;
}

export function NeedsUserCard({ payload, onSelect, disabled }: NeedsUserCardProps) {
  const { answer, options, diff_summary, touched_paths } = payload;

  return (
    <div className="my-2 rounded-lg border border-amber-200 bg-card shadow-sm">
      <div className="flex items-start gap-2 border-b border-amber-100 bg-gradient-to-r from-amber-50 to-orange-50 px-4 py-3">
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
        <div className="flex-1 text-sm text-amber-900 prose prose-sm max-w-none [&_p]:my-1 [&_p]:leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
        </div>
      </div>

      {(diff_summary || (touched_paths && touched_paths.length > 0)) && (
        <div className="border-b bg-muted/30 px-4 py-2 text-[11px] text-muted-foreground">
          {touched_paths && touched_paths.length > 0 && (
            <div className="mb-1 flex flex-wrap items-center gap-1">
              <span className="font-medium">Files touched:</span>
              {touched_paths.slice(0, 4).map((p) => (
                <code
                  key={p}
                  className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]"
                >
                  {p}
                </code>
              ))}
              {touched_paths.length > 4 && (
                <span>+{touched_paths.length - 4} more</span>
              )}
            </div>
          )}
          {diff_summary && (
            <div className="font-mono text-[10px]">{diff_summary}</div>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1.5 p-3">
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Your call
        </div>
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onSelect(opt)}
            disabled={disabled}
            className="group flex w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-left text-xs font-medium text-foreground hover:border-amber-300 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="truncate">{opt}</span>
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground group-hover:text-amber-700" />
          </button>
        ))}
      </div>
    </div>
  );
}
