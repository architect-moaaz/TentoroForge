"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import type { ResourceCard } from "@/stores/chat";
import { useFlavorText } from "@/lib/flavor-text";
import { DeliverablesPanel } from "@/components/generation/DeliverablesPanel";

/**
 * Dev-only preview of the generation progress UX (flavor ticker + deliverables
 * tracker + live preview cards). Mounts the REAL components and replays a
 * scripted build, so it's a faithful view without running the backend.
 * Visit /progress-preview.
 */

type Step = { status: string; card?: ResourceCard; delay?: number };

const SCRIPT: Step[] = [
  { status: "Preparing the plan", delay: 900 },
  { status: "Plan ready — defining data models", delay: 700 },
  { status: "Data model definition done", card: { kind: "data_model", name: "Patient", state: "done", index: 1, total: 5, summary: "12 fields" } },
  { status: "Generating data models", card: { kind: "data_model", name: "Dentist", state: "done", index: 2, total: 5, summary: "9 fields" } },
  { status: "Generating data models", card: { kind: "data_model", name: "Appointment", state: "done", index: 3, total: 5, summary: "10 fields · FK: patient, dentist" } },
  { status: "Generating data models", card: { kind: "data_model", name: "Invoice", state: "done", index: 4, total: 5, summary: "11 fields · FK: patient" } },
  { status: "Data models generated", card: { kind: "data_model", name: "InsuranceClaim", state: "done", index: 5, total: 5, summary: "8 fields · FK: invoice" } },
  { status: "Workflow planning in progress", card: { kind: "workflow", name: "AppointmentStatusWorkflow", state: "done", index: 1, total: 4, summary: "trigger: appointment status change · 8 steps" }, delay: 1000 },
  { status: "Generating workflows", card: { kind: "workflow", name: "InvoicePaymentWorkflow", state: "done", index: 2, total: 4, summary: "trigger: invoice action · 8 steps" } },
  { status: "Generating workflows", card: { kind: "workflow", name: "InsuranceClaimWorkflow", state: "done", index: 3, total: 4, summary: "trigger: insurance claim review · 11 steps" } },
  { status: "Workflows generated", card: { kind: "workflow", name: "18 CRUD workflows", state: "done", index: 4, total: 4, summary: "Create / Update / Delete per entity" } },
  { status: "Assembling pages", card: { kind: "page", name: "/dashboard", state: "done", index: 1, total: 3, summary: "Table · Chart · MetricTile · 51 nodes" }, delay: 1000 },
  { status: "Assembling pages", card: { kind: "page", name: "/appointments", state: "done", index: 2, total: 3, summary: "Calendar · Table · 43 nodes" } },
  { status: "Pages assembled", card: { kind: "page", name: "/invoices", state: "done", index: 3, total: 3, summary: "Table · DescriptionList · 29 nodes" } },
  { status: "Binding actions to workflows", card: { kind: "binding", name: "Confirm → AppointmentStatusWorkflow", state: "done", summary: "args: targetStatus = confirmed" }, delay: 1000 },
  { status: "Binding in progress", card: { kind: "binding", name: "Cancel → AppointmentStatusWorkflow", state: "done", summary: "args: targetStatus = cancelled" } },
  { status: "Bindings complete — build ready", delay: 600 },
];

export default function ProgressPreviewPage() {
  const [resources, setResources] = useState<ResourceCard[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const gerund = useFlavorText(isGenerating);

  const run = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setResources([]);
    setStatus(null);
    setIsGenerating(true);

    let t = 0;
    SCRIPT.forEach((step) => {
      t += step.delay ?? 550;
      timers.current.push(
        setTimeout(() => {
          setStatus(step.status);
          if (step.card) setResources((prev) => [...prev, step.card!]);
        }, t),
      );
    });
    timers.current.push(setTimeout(() => setIsGenerating(false), t + 700));
  }, []);

  useEffect(() => {
    run();
    return () => timers.current.forEach(clearTimeout);
  }, [run]);

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Generation progress — preview</h1>
          <p className="text-sm text-muted-foreground">
            The real flavor ticker, deliverables tracker, and live preview cards,
            replaying a scripted build.
          </p>
        </div>
        <button
          onClick={run}
          className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Replay
        </button>
      </div>

      {/* Mirrors the chat SSE status bar where this renders in production */}
      <div className="overflow-hidden rounded-xl border">
        <div className="bg-muted/40 px-3 py-2">
          <div className="flex items-center gap-2">
            {isGenerating && (
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
                <Loader2 className="h-3 w-3 animate-spin text-primary" />
                {gerund}…
              </span>
            )}
            {status && (
              <span className="truncate text-[11px] text-muted-foreground">{status}</span>
            )}
            {!isGenerating && !status && (
              <span className="text-[11px] text-muted-foreground">Idle</span>
            )}
          </div>
          <DeliverablesPanel resources={resources} isGenerating={isGenerating} />
        </div>
      </div>
    </div>
  );
}
