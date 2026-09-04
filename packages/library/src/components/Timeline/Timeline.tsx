import * as React from "react";
import type { TimelineNode } from "@tentoroforge/schema";
import { z } from "zod";

type Props = z.infer<typeof TimelineNode>["props"];

const STATUS_DOT: Record<string, string> = {
  pending:   "bg-amber-500",
  approved:  "bg-emerald-500",
  rejected:  "bg-rose-500",
  completed: "bg-emerald-500",
  info:      "bg-blue-500",
};

export function Timeline({ entries, orientation = "vertical" }: Props) {
  // entries can now be a Mustache binding string OR an array (including empty default)
  const list = Array.isArray(entries) ? entries : [];
  const isUnresolvedBinding = typeof entries === "string";

  if (isUnresolvedBinding) {
    return (
      <p className="px-3 py-6 text-center text-xs italic text-muted-foreground/70">
        Timeline binding {entries} — no fixture data available
      </p>
    );
  }

  if (list.length === 0) {
    return (
      <p className="px-3 py-6 text-center text-xs text-muted-foreground">No activity yet.</p>
    );
  }

  if (orientation === "horizontal") {
    return (
      <ol className="flex items-start gap-3 overflow-x-auto pb-2">
        {list.map((e) => (
          <li key={e.id} className="flex-shrink-0 w-48 border-s-2 border-border ps-3">
            <div className={`h-2 w-2 rounded-full ${STATUS_DOT[e.status ?? "info"] ?? STATUS_DOT.info} -ms-4 mb-1`} />
            <p className="text-xs text-muted-foreground">{new Date(e.timestamp).toLocaleString("en-US")}</p>
            <p className="text-sm font-medium">{e.title}</p>
            {e.actor && <p className="text-xs text-muted-foreground">{e.actor}</p>}
            {e.detail && <p className="mt-1 text-xs text-muted-foreground">{e.detail}</p>}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="space-y-3">
      {list.map((e) => (
        <li key={e.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className={`h-3 w-3 rounded-full ${STATUS_DOT[e.status ?? "info"] ?? STATUS_DOT.info} mt-1.5`} />
            <div className="flex-1 w-px bg-border mt-1" />
          </div>
          <div className="flex-1 pb-3">
            <p className="text-xs text-muted-foreground">{new Date(e.timestamp).toLocaleString("en-US")}</p>
            <p className="text-sm font-medium">{e.title}</p>
            {e.actor && <p className="text-xs text-muted-foreground">— {e.actor}</p>}
            {e.detail && <p className="mt-1 text-xs text-muted-foreground">{e.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
