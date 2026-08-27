"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Sparkles,
  Wrench,
  HelpCircle,
  Undo2,
  FileCode2,
  Database,
  Cog,
} from "lucide-react";

/** A slash command available in the chat composer. `insert` is what the
 *  input text becomes after the user picks the command — `caret` marks
 *  where the input's cursor should land (a `⎽` character in the string
 *  is replaced with an empty gap for the cursor). */
export type SlashCommand = {
  id: string;
  trigger: string;      // "/add-page"
  label: string;        // "Add a page"
  description: string;  // "Create a new page in the app"
  icon: React.ComponentType<{ className?: string }>;
  /** Template inserted when the command is picked. `⎽` marks where the
   *  cursor should end up so the user can immediately type the argument
   *  (e.g. the entity name). */
  insert: string;
};

/** The canonical command list. Keep entries short — the palette is
 *  scanned quickly. */
export const SLASH_COMMANDS: SlashCommand[] = [
  {
    id: "add-page",
    trigger: "/add-page",
    label: "Add a page",
    description: "Create a whole new page via the pipeline's builders",
    icon: Sparkles,
    insert: "Add a new page: ⎽",
  },
  {
    id: "add-workflow",
    trigger: "/add-workflow",
    label: "Add a workflow",
    description: "Create a Create/Update/Delete workflow for an entity",
    icon: Cog,
    insert: "Add a workflow: ⎽",
  },
  {
    id: "add-entity",
    trigger: "/add-entity",
    label: "Add an entity",
    description: "Add a new data model + Drizzle schema",
    icon: Database,
    insert: "Add an entity: ⎽",
  },
  {
    id: "fix",
    trigger: "/fix",
    label: "Fix a bug",
    description: "Describe what's broken and I'll diagnose it",
    icon: Wrench,
    insert: "Fix: ⎽",
  },
  {
    id: "explain",
    trigger: "/explain",
    label: "Explain something",
    description: "How does a workflow, page, or component work?",
    icon: FileCode2,
    insert: "Explain: ⎽",
  },
  {
    id: "undo",
    trigger: "/undo",
    label: "Undo",
    description: "Revert my last applied change",
    icon: Undo2,
    insert: "undo",
  },
  {
    id: "help",
    trigger: "/help",
    label: "What can you do?",
    description: "Quick summary of Smith's capabilities",
    icon: HelpCircle,
    insert: "What can you do?",
  },
];

/** When `value` starts with '/' and doesn't yet contain a space, we're
 *  in slash-command mode; the palette is visible and filters by the
 *  characters typed after the '/'. Once the user hits space or a
 *  non-command message shape, the palette closes. */
export function useSlashCommandFilter(value: string): {
  active: boolean;
  matches: SlashCommand[];
  query: string;
} {
  return useMemo(() => {
    if (!value.startsWith("/")) return { active: false, matches: [], query: "" };
    // Only active while there's no whitespace and the total length is
    // short-ish (commands are short; a long "/something" is probably a
    // regular sentence starting with a slash).
    if (/\s/.test(value)) return { active: false, matches: [], query: "" };
    const q = value.slice(1).toLowerCase();
    const filtered = SLASH_COMMANDS.filter((c) =>
      c.id.startsWith(q) || c.trigger.slice(1).startsWith(q)
    );
    return { active: true, matches: filtered, query: q };
  }, [value]);
}

interface SlashCommandPaletteProps {
  matches: SlashCommand[];
  /** Called when the user picks a command. Consumer decides what to do
   *  with `insert` (typically: setValue + focus + place caret). */
  onPick: (cmd: SlashCommand) => void;
  /** Currently-highlighted match index. */
  activeIndex: number;
  onHover: (index: number) => void;
}

export function SlashCommandPalette({
  matches,
  onPick,
  activeIndex,
  onHover,
}: SlashCommandPaletteProps) {
  const listRef = useRef<HTMLUListElement>(null);

  // Ensure the active item stays in view when the user arrow-keys past
  // the visible window.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const active = list.querySelector<HTMLElement>('[data-active="true"]');
    if (active) active.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (matches.length === 0) {
    return (
      <div className="absolute bottom-full left-0 right-0 mb-2 rounded-xl border bg-popover px-3 py-2 text-xs text-muted-foreground shadow-lg">
        No matching commands. Type <code className="rounded bg-muted px-1">/help</code> for the full list.
      </div>
    );
  }

  return (
    <ul
      ref={listRef}
      role="listbox"
      className="absolute bottom-full left-0 right-0 mb-2 max-h-72 overflow-y-auto rounded-xl border bg-popover py-1 shadow-lg"
    >
      {matches.map((cmd, i) => {
        const isActive = i === activeIndex;
        const Icon = cmd.icon;
        return (
          <li
            key={cmd.id}
            role="option"
            aria-selected={isActive}
            data-active={isActive}
            onMouseEnter={() => onHover(i)}
            onMouseDown={(e) => {
              // mousedown (not click) so we can pick BEFORE the textarea
              // loses focus, avoiding a flicker.
              e.preventDefault();
              onPick(cmd);
            }}
            className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 transition-colors ${
              isActive ? "bg-accent" : "hover:bg-muted/60"
            }`}
          >
            <span
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
                isActive
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <code className="rounded bg-muted px-1 text-[10px] font-medium text-foreground">
                  {cmd.trigger}
                </code>
                <span className="text-xs font-medium text-foreground">
                  {cmd.label}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {cmd.description}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
