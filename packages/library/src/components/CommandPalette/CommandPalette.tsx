"use client";

import * as React from "react";
import { Command } from "cmdk";
import { z } from "zod";
import type { CommandPaletteNode } from "@tentoroforge/schema";
import { WorkflowDispatcherContext, useNavigator } from "@tentoroforge/renderer";
import { useDesignTime } from "@tentoroforge/renderer";

type Props = z.infer<typeof CommandPaletteNode>["props"];

/**
 * Does this keydown match the palette's advertised shortcut?
 *
 * `e.key === triggerKey` was three different bugs in one comparison:
 *   - case: with Caps Lock or a Shift-modified layout `e.key` is `"K"`, and the
 *     seed is `"k"`, so the shortcut the button's own face advertises missed;
 *   - layout: on a Dvorak/AZERTY/Cyrillic keyboard `e.key` is not the Latin
 *     letter at all, so `Ctrl+K` was unreachable for those users;
 *   - a stray space in the free-text `triggerKey` control silently disabled it.
 * `e.code` ("KeyK") is the physical key and covers the last two.
 */
function matchesTrigger(e: KeyboardEvent, triggerKey: string): boolean {
  const want = (triggerKey ?? "").trim().toLowerCase();
  if (!want) return false;
  if ((e.key ?? "").toLowerCase() === want) return true;
  return want.length === 1 && e.code === `Key${want.toUpperCase()}`;
}

export function CommandPalette({ items, placeholder = "Type a command or search…", triggerKey = "k" }: Props) {
  const [open, setOpen] = React.useState(false);
  const nav = useNavigator();
  const dispatchWorkflow = React.useContext(WorkflowDispatcherContext);
  // THE EDITOR'S KEYBOARD IS NOT THIS COMPONENT'S TO TAKE.
  //
  // A document-level `keydown` listener on a node sitting in an authoring
  // canvas is the round-4/5 trap: every dropped palette would fight the editor
  // for Ctrl+K, and the audit specifically recorded that it does NOT do that
  // today as a thing worth keeping. Making the shortcut work and keeping the
  // canvas out of it are the same requirement, so the listener is registered
  // only where the tree is being RUN. Same seam as the canvas's pointer-down
  // suppression, one layer up.
  const designTime = useDesignTime();
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    if (designTime) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && matchesTrigger(e, triggerKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [triggerKey, open, designTime]);

  // FOCUS FOLLOWS THE PALETTE.
  //
  // On open, `document.activeElement` stayed on BODY: a keyboard user had to
  // reach for the mouse before they could type into a search box that had just
  // appeared in front of them. On close, focus was left nowhere at all, which
  // drops the user back to the top of the document. Both halves are one rule —
  // a modal owns focus while it is up and gives it back when it goes down.
  const wasOpen = React.useRef(false);
  React.useEffect(() => {
    if (open) {
      wasOpen.current = true;
      const t = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
    // Only give focus BACK — never take it on first mount, which would move the
    // caret out of whatever the page had focused just because a palette exists
    // somewhere on it.
    if (wasOpen.current) {
      wasOpen.current = false;
      triggerRef.current?.focus?.();
    }
  }, [open]);

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
        ref={triggerRef}
        aria-haspopup="dialog"
        aria-expanded={false}
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
      {/* THE OVERLAY WAS A PLAIN DIV.
          It covers the whole viewport, swallows the click that closes it and
          takes the keyboard — every behaviour of a modal — while announcing
          itself as nothing at all. A screen-reader user got a page that had
          silently stopped responding. `role="dialog"` + `aria-modal` go on the
          PANEL, not on the backdrop: the backdrop is the scrim, and marking it
          would put the dialog boundary around a click-to-dismiss surface. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl rounded-lg border border-border bg-popover shadow-2xl"
      >
        <Command label="Command palette" className="flex flex-col">
          <Command.Input
            ref={inputRef}
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
                        // WAS `window.location.assign(to)`.
                        //
                        // That is the same line six other components used to
                        // carry, and it resolves an app-absolute route against
                        // the ORIGIN root — so "Go to dashboard" on
                        // /p/<project>/<page> landed on the origin's "/" and
                        // 404'd, exactly as the audit reported. Every other
                        // schema-driven navigation goes through `useNavigator`,
                        // which is where the base path is applied; this one was
                        // simply missed. It also gets soft navigation for free.
                        nav.push(item.action.to);
                      } else {
                        // Workflow — prefer the host's dispatcher, which is the
                        // same seam Link/Button use. The window event stays as
                        // the fallback for hosts that listen for it rather than
                        // providing a dispatcher, so nothing that worked stops.
                        if (dispatchWorkflow) {
                          dispatchWorkflow(item.action.workflow);
                        } else {
                          window.dispatchEvent(new CustomEvent("command-palette:workflow", {
                            detail: { workflow: item.action.workflow, itemId: item.id },
                          }));
                        }
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
