"use client";

/**
 * The small page furniture the Insights sections share: a titled section, an empty note, a headline figure, and a chart card with a
 * Chart / Table switch. Kept apart from the panel so the people section and the live setup card use exactly the same pieces.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

export function Section({ title, id, hint, children }: { title: string; id: string; hint?: string; children: ReactNode }) {
  return (
    <section data-testid={`insights-section-${id}`} aria-labelledby={`insights-h-${id}`}>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h4 id={`insights-h-${id}`} className="text-sm font-semibold">{title}</h4>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">{children}</p>;

/** A figure with its words and, underneath, the one small picture that makes it readable at a glance. The value is in plain proportional figures. */
export function StatTile({
  id, label, value, sub, tone, prefix, children,
}: { id: string; label: string; value: string; sub: string; tone?: "warn"; /** A small word before the figure, such as "about". */ prefix?: string; children?: ReactNode }) {
  return (
    <div className={`min-w-0 rounded-xl border p-3.5 shadow-sm ${tone === "warn" ? "border-amber-300 bg-amber-50" : "bg-white"}`} data-testid={`insights-card-${id}`}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[28px] font-semibold leading-none tracking-tight">
        {prefix && <span className="mr-1.5 text-sm font-normal text-muted-foreground">{prefix}</span>}
        {value}
      </div>
      {sub && <div className="mt-1.5 text-[11px] text-muted-foreground">{sub}</div>}
      {children}
    </div>
  );
}

/**
 * A chart in its card: a title and one quiet line saying what is drawn, and a Chart / Table switch, so every chart has a table with the
 * same numbers for anyone who cannot or would rather not read a drawing. Nothing is only in a tooltip.
 */
export function ChartCard({
  id, title, subtitle, empty, table, children,
}: { id: string; title: string; subtitle: string; empty: string | null; table: ReactNode; children: ReactNode; plain?: boolean }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="min-w-0 rounded-xl border bg-white p-4 shadow-sm" data-testid={`insights-section-${id}`} aria-labelledby={`insights-h-${id}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 id={`insights-h-${id}`} className="text-sm font-semibold">{title}</h4>
          <p className="text-[11px] text-muted-foreground">{subtitle}</p>
        </div>
        {!empty && (
          <div className="flex shrink-0 gap-0.5 rounded-md border p-0.5" role="group" aria-label={`How to show ${title}`}>
            <button type="button" aria-pressed={!asTable} onClick={() => setAsTable(false)} className={`rounded px-2 py-0.5 text-[11px] ${!asTable ? "bg-slate-900 text-white" : "text-muted-foreground hover:bg-muted"}`}>
              Chart
            </button>
            <button type="button" aria-pressed={asTable} onClick={() => setAsTable(true)} className={`rounded px-2 py-0.5 text-[11px] ${asTable ? "bg-slate-900 text-white" : "text-muted-foreground hover:bg-muted"}`}>
              Table
            </button>
          </div>
        )}
      </div>
      {empty ? <Empty>{empty}</Empty> : asTable ? table : children}
    </section>
  );
}

/**
 * A button that puts `text` on the clipboard and says "Copied" for two seconds (or that it could not). The text is read only at the
 * moment of the click and is never kept in this component's state, so a secret passed in is not held here after the click.
 */
export function CopyButton({ text, label = "Copy", ariaLabel, className = "" }: { text: string; label?: string; ariaLabel?: string; className?: string }) {
  const [result, setResult] = useState<"copied" | "failed" | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const onClick = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      ok = false;
    }
    setResult(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setResult(null), 2000);
  };
  return (
    <button
      type="button"
      onClick={() => void onClick()}
      aria-label={ariaLabel}
      className={`rounded border px-2 py-0.5 text-[11px] hover:bg-muted ${className}`}
    >
      {result === "copied" ? "Copied" : result === "failed" ? "Could not copy" : label}
    </button>
  );
}
