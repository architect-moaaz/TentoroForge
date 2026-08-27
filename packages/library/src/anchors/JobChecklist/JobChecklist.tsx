"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * JobChecklist — field-worker step list. Big touch targets, high contrast,
 * one thing at a time visible. Each step: number, label, optional detail,
 * completion toggle. Not a form — a walk-me-through.
 */
export const JobChecklistProps = z.object({
  title: z.string().optional(),
  steps: z.array(z.object({
    label: z.string(),
    detail: z.string().optional(),
    done: z.boolean().optional(),
    navigate: z.string().optional(),
  })).min(1).max(20).optional(),
});
export type JobChecklistPropsType = z.infer<typeof JobChecklistProps>;

type _JC = NonNullable<JobChecklistPropsType["steps"]>[number];
export function JobChecklist({ title, steps }: JobChecklistPropsType) {
  const rows: _JC[] = steps && steps.length > 0 ? steps : Array.from({ length: 4 }, () => ({ label: "" } as _JC));
  const doneCount = rows.filter(r => r.done).length;
  return (
    <section
      data-anchor="job_checklist"
      className="rounded-2xl border border-border bg-card overflow-hidden"
    >
      <header className="flex items-baseline justify-between px-5 py-4 border-b border-border">
        <h3
          className="text-base font-semibold tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Steps"}
        </h3>
        <span className="text-sm text-muted-foreground tabular-nums">
          {doneCount}/{rows.length}
        </span>
      </header>
      <ol className="flex flex-col">
        {rows.map((s, i) => (
          <li key={i}>
            <a
              href={s.navigate || "#"}
              className={`grid grid-cols-[3rem_1fr_auto] items-center gap-4 px-5 py-4 border-b border-border last:border-b-0 transition ${
                s.done ? "bg-green-500/5" : "hover:bg-accent/50"
              }`}
            >
              <span
                className={`h-10 w-10 rounded-full grid place-items-center text-base font-semibold ${
                  s.done
                    ? "bg-green-500 text-white"
                    : "bg-primary/15 text-primary"
                }`}
                aria-hidden="true"
              >
                {s.done ? "✓" : i + 1}
              </span>
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className={`text-base font-medium ${s.done ? "text-muted-foreground line-through" : "text-foreground"}`}>
                  {s.label || <span className={skeleton("w-40")} />}
                </span>
                {s.detail && (
                  <span className="text-xs text-muted-foreground truncate">{s.detail}</span>
                )}
              </div>
              <span className="text-muted-foreground text-lg" aria-hidden="true">→</span>
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}
