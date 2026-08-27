"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { StepperPropsType } from "./Stepper.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface StepperProps extends StepperPropsType {
  style?: StyleSlotT;
}

type Status = "pending" | "active" | "current" | "complete" | "done" | "error" | "skipped";

const DONE = new Set<Status>(["complete", "done"]);
const ACTIVE = new Set<Status>(["active", "current"]);

function colorFor(status: Status | undefined): string {
  if (!status) return "var(--color-border-strong, #cbd5e1)";
  if (DONE.has(status)) return "var(--color-primary-500)";
  if (ACTIVE.has(status)) return "var(--color-primary-500)";
  if (status === "error") return "var(--color-danger-500, #ef4444)";
  if (status === "skipped") return "var(--color-border-strong, #cbd5e1)";
  return "var(--color-border-strong, #cbd5e1)";
}

function glyph(status: Status | undefined, index: number): string {
  if (status && DONE.has(status)) return "✓";
  if (status === "error") return "!";
  if (status === "skipped") return "–";
  return String(index + 1);
}

/**
 * Generic process stepper — numbered stages with connectors, coloured by status.
 * Unlike ApprovalStepper (approve/reject semantics), status is free: pending /
 * active / complete / error / skipped, and `activeStep` derives status for steps
 * that omit it (index < active → complete, == active → current, > active → pending).
 */
export function Stepper({ steps, orientation = "horizontal", activeStep, activeId, style }: StepperProps) {
  const list = Array.isArray(steps) ? steps : [];
  // `activeId` resolves a bound status string ("queued") to its step
  // index by id or label; an explicit numeric `activeStep` wins.
  const fold = (v: unknown) => String(v ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
  let active = activeStep;
  if (active == null && activeId) {
    const idx = list.findIndex(
      (s) => fold(s.id) === fold(activeId) || fold(s.label) === fold(activeId),
    );
    if (idx >= 0) active = idx;
  }
  const derived = (i: number, s?: Status): Status | undefined => {
    if (s) return s;
    if (active == null) return undefined;
    return i < active ? "complete" : i === active ? "current" : "pending";
  };
  const vertical = orientation === "vertical";

  return (
    <div
      className={vertical ? "flex flex-col" : "flex items-start"}
      data-stepper=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {list.map((step, i) => {
        const status = derived(i, step.status as Status | undefined);
        const color = colorFor(status);
        const filled = status && (DONE.has(status) || ACTIVE.has(status));
        const last = i === list.length - 1;
        return (
          <div key={step.id ?? i} className={vertical ? "flex gap-3" : "flex flex-1 flex-col items-center text-center"}>
            {vertical ? (
              <div className="flex flex-col items-center">
                <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold"
                  style={{ borderColor: color, backgroundColor: filled ? color : "transparent", color: filled ? "#fff" : color }}>
                  {glyph(status, i)}
                </span>
                {!last && <span className="my-1 w-0.5 flex-1" style={{ backgroundColor: color, minHeight: 24 }} />}
              </div>
            ) : (
              <div className="flex w-full items-center">
                <span className="h-0.5 flex-1" style={{ backgroundColor: i === 0 ? "transparent" : color }} />
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold"
                  style={{ borderColor: color, backgroundColor: filled ? color : "transparent", color: filled ? "#fff" : color }}>
                  {glyph(status, i)}
                </span>
                <span className="h-0.5 flex-1" style={{ backgroundColor: last ? "transparent" : color }} />
              </div>
            )}
            <div className={vertical ? "pb-4" : "mt-1"}>
              <div className="text-xs font-medium text-foreground">{step.label}</div>
              {step.description && <div className="text-[10px] text-muted-foreground">{step.description}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
