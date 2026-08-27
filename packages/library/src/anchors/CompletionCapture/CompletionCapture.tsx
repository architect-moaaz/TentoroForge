"use client";
import * as React from "react";
import { z } from "zod";

/**
 * CompletionCapture — field-worker "job done" surface. Photo capture,
 * signature slot, notes. Not an editor — a proof-of-completion stub
 * that hands off to a form/workflow on submit.
 */
export const CompletionCaptureProps = z.object({
  title: z.string().optional(),
  photoLabel: z.string().optional(),
  signatureLabel: z.string().optional(),
  notesLabel: z.string().optional(),
  submitLabel: z.string().optional(),
  submitNavigate: z.string().optional(),
});
export type CompletionCapturePropsType = z.infer<typeof CompletionCaptureProps>;

export function CompletionCapture(props: CompletionCapturePropsType) {
  const {
    title, photoLabel, signatureLabel, notesLabel, submitLabel, submitNavigate,
  } = props;
  return (
    <section
      data-anchor="completion_capture"
      className="rounded-2xl border border-border bg-card p-6 flex flex-col gap-4"
    >
      <h3
        className="text-lg font-semibold tracking-tight text-foreground"
        style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
      >
        {title || "Wrap up"}
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <button
          type="button"
          className="flex flex-col items-center justify-center gap-2 aspect-video rounded-xl border-2 border-dashed border-border bg-muted/40 hover:border-primary/50 hover:bg-accent transition text-muted-foreground"
        >
          <span className="text-3xl" aria-hidden="true">📷</span>
          <span className="text-sm font-medium">{photoLabel || "Add photo"}</span>
        </button>
        <button
          type="button"
          className="flex flex-col items-center justify-center gap-2 aspect-video rounded-xl border-2 border-dashed border-border bg-muted/40 hover:border-primary/50 hover:bg-accent transition text-muted-foreground"
        >
          <span className="text-3xl" aria-hidden="true">✍</span>
          <span className="text-sm font-medium">{signatureLabel || "Signature"}</span>
        </button>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          {notesLabel || "Notes"}
        </span>
        <textarea
          rows={3}
          className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="Anything the next person should know?"
        />
      </label>
      <a
        href={submitNavigate || "#"}
        className="mt-2 inline-flex items-center justify-center h-12 rounded-full bg-primary text-primary-foreground text-base font-semibold hover:brightness-110 transition"
      >
        {submitLabel || "Mark complete"}
      </a>
    </section>
  );
}
