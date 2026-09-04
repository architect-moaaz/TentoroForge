"use client";

import * as React from "react";
import { Command } from "cmdk";
import { z } from "zod";
import type { CommandPaletteNode } from "@tentoroforge/schema";

type Props = z.infer<typeof CommandPaletteNode>["props"];

export function CommandPalette({ items, placeholder = "Type a command or search…", triggerKey = "k" }: Props) {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === triggerKey) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [triggerKey, open]);

  // Group items by group prop
  const groups = React.useMemo(() => {
    const out: Record<string, typeof items> = {};
    for (const item of items) {
      const g = item.group ?? "General";
      if (!out[g]) out[g] = [];
      out[g].push(item);
    }
    return out;
  }, [items]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 text-xs text-muted-foreground hover:bg-muted/60"
        title={`Open command palette (${typeof navigator !== "undefined" && navigator?.platform?.includes("Mac") ? "⌘" : "Ctrl"}+${triggerKey.toUpperCase()})`}
      >
        <span>Search…</span>
        <kbd className="rounded border border-border bg-background px-1 font-mono text-[10px]">
          {typeof navigator !== "undefined" && navigator?.platform?.includes("Mac") ? "⌘" : "Ctrl"}+{triggerKey.toUpperCase()}
        </kbd>
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/20 backdrop-blur-sm pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl rounded-lg border border-border bg-popover shadow-2xl"
      >
        <Command label="Command palette" className="flex flex-col">
          <Command.Input
            placeholder={placeholder}
            className="h-12 w-full bg-transparent px-4 text-sm outline-none border-b border-border"
          />
          <Command.List className="max-h-[400px] overflow-auto p-1">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results.
            </Command.Empty>
            {Object.entries(groups).map(([groupName, groupItems]) => (
              <Command.Group key={groupName} heading={groupName} className="text-[10px] uppercase tracking-wide text-muted-foreground px-2 pt-2">
                {groupItems.map((item) => (
                  <Command.Item
                    key={item.id}
                    value={`${item.label} ${item.group ?? ""}`}
                    onSelect={() => {
                      if (item.action.type === "navigate") {
                        window.location.assign(item.action.to);
                      } else {
                        // Workflow — emit a custom event so the host can handle dispatch
                        window.dispatchEvent(new CustomEvent("command-palette:workflow", {
                          detail: { workflow: item.action.workflow, itemId: item.id },
                        }));
                      }
                      setOpen(false);
                    }}
                    className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-muted aria-selected:bg-muted"
                  >
                    <span>{item.label}</span>
                    {item.shortcut && (
                      <kbd className="ms-2 rounded border border-border bg-background px-1.5 font-mono text-[10px] text-muted-foreground">
                        {item.shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
