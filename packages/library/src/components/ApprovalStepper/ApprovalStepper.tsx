import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { z } from "zod";
import type { ApprovalStepperNode } from "@tentoroforge/schema";

/** The renderer passes the node's `style` envelope alongside its props.
 *  WITHOUT `style` here the Style panel wrote background / padding /
 *  radius / shadow / motion into the page schema and this component
 *  rendered none of it — the edit persisted to disk and was invisible on
 *  the canvas, which reads as a broken Style tab rather than an
 *  unsupported one. */
type Props = z.infer<typeof ApprovalStepperNode>["props"] & { style?: StyleSlotT };

const STATUS_DOT: Record<string, string> = {
  pending:  "bg-muted text-muted-foreground border border-border",
  current:  "bg-primary text-primary-foreground border-2 border-primary ring-2 ring-primary/20",
  approved: "bg-emerald-600 text-white",
  rejected: "bg-rose-600 text-white",
  skipped:  "bg-muted text-muted-foreground/60 border border-dashed border-border",
};

const STATUS_GLYPH: Record<string, string> = {
  pending:  "",
  current:  "●",
  approved: "✓",
  rejected: "✕",
  skipped:  "—",
};

const STATUS_CONNECTOR: Record<string, string> = {
  pending: "bg-border",
  current: "bg-primary/30",
  approved: "bg-emerald-600",
  rejected: "bg-rose-600",
  skipped: "bg-border opacity-50",
};

export function ApprovalStepper({ steps, orientation = "horizontal", style }: Props) {
  if (orientation === "vertical") {
    return (
      <ol className="space-y-4" style={resolveStyle(style)} {...useMotion(style?.motion)}>
        {/* `StepperStep.id` is optional and the seeded default carries none, so
            keying on it alone gave every row key={undefined} and a React
            warning on drop. Index fallback, same as Timeline. */}
        {steps.map((step, idx) => (
          <li key={step.id ?? idx} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${STATUS_DOT[step.status]}`}>
                {STATUS_GLYPH[step.status] || (idx + 1)}
              </div>
              {idx < steps.length - 1 && (
                <div className={`flex-1 w-0.5 mt-1 ${STATUS_CONNECTOR[steps[idx + 1]?.status === "pending" ? "pending" : step.status]}`} style={{ minHeight: 24 }} />
              )}
            </div>
            <div className="flex-1 pb-2">
              <p className="text-sm font-medium leading-tight">{step.label}</p>
              {step.actor && <p className="text-xs text-muted-foreground mt-0.5">{step.actor}</p>}
              {step.timestamp && (
                <p className="text-[11px] text-muted-foreground/80 mt-0.5">
                  {new Date(step.timestamp).toLocaleString("en-US")}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="flex items-start w-full" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {steps.map((step, idx) => (
        <li key={step.id ?? idx} className="flex flex-1 flex-col items-center relative">
          <div className="flex items-center w-full">
            <div className={`flex-1 h-0.5 ${idx === 0 ? "invisible" : STATUS_CONNECTOR[step.status]}`} />
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${STATUS_DOT[step.status]}`}>
              {STATUS_GLYPH[step.status] || (idx + 1)}
            </div>
            <div className={`flex-1 h-0.5 ${idx === steps.length - 1 ? "invisible" : STATUS_CONNECTOR[steps[idx + 1]?.status === "pending" ? "pending" : step.status]}`} />
          </div>
          <div className="text-center mt-2 px-1 max-w-[140px]">
            <p className="text-xs font-medium leading-tight">{step.label}</p>
            {step.actor && <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{step.actor}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
