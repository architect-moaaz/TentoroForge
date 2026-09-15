"use client";

/**
 * Dev preview of Smith Chat's "working" indicator (ThinkingTrail): the forge
 * icon, the present-participle activity name, and the live elapsed clock. Steps
 * through a few states so it can be seen without driving a live build. No login:
 * it is a /dev route.
 */
import { useState } from "react";
import { ThinkingTrail } from "@/components/smith/SmithPanel";
import type { RunNode, RunThought } from "@/hooks/useBlueprintRun";

const node = (key: string, state: RunNode["state"]): RunNode => ({
  key,
  state,
  calls: 0,
});

const STATES: Record<
  string,
  { thoughts: RunThought[]; nodes: RunNode[]; busy: boolean }
> = {
  "Thinking (chat turn)": { thoughts: [{ kind: "reasoning", text: "…" }], nodes: [], busy: true },
  "Composing the screens": {
    thoughts: [],
    nodes: [node("requirements", "done"), node("page_layouts", "running")],
    busy: true,
  },
  "Generating the frontend": {
    thoughts: [
      { kind: "step", text: "Modelling the product", node: "application_model" },
      { kind: "step", text: "Generating the frontend", node: "frontend" },
    ],
    nodes: [node("frontend", "running")],
    busy: true,
  },
  "Idle (renders nothing)": { thoughts: [], nodes: [], busy: false },
};

export default function ThinkingTrailPreview() {
  const [which, setWhich] = useState<keyof typeof STATES>("Composing the screens");
  const s = STATES[which];
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="text-sm font-semibold">Smith working indicator — preview</h1>
        <div className="flex flex-wrap gap-2">
          {Object.keys(STATES).map((k) => (
            <button
              key={k}
              onClick={() => setWhich(k as keyof typeof STATES)}
              className={
                "rounded border px-2 py-1 text-xs " +
                (k === which ? "border-primary text-primary" : "text-muted-foreground")
              }
            >
              {k}
            </button>
          ))}
        </div>
        <div className="rounded-lg border bg-background p-4">
          <ThinkingTrail thoughts={s.thoughts} nodes={s.nodes} busy={s.busy} />
        </div>
      </div>
    </div>
  );
}
