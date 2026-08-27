"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  MessageSquare,
  Eye,
  Code,
  Database,
  Shield,
  Workflow,
  PaintBucket,
  Map,
  Bot,
  Sparkles,
  GitBranch,
  Download,
  Search,
  Command,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { CommandItem } from "@/types/portal";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: CommandItem[];
}

const CATEGORY_ORDER = [
  "navigation",
  "action",
  "model",
  "page",
  "workflow",
  "rule",
  "component",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  navigation: "Navigation",
  action: "Actions",
  model: "Data Models",
  page: "Pages",
  workflow: "Workflows",
  rule: "Rules",
  component: "Components",
};

function fuzzyMatch(query: string, text: string): boolean {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;

  // Simple fuzzy: each char of query must appear in order in text
  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length;
}

export function CommandPalette({
  open,
  onOpenChange,
  items,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const filtered = useMemo(() => {
    if (!query) return items;
    return items.filter(
      (item) =>
        fuzzyMatch(query, item.label) ||
        (item.description && fuzzyMatch(query, item.description)) ||
        fuzzyMatch(query, item.category),
    );
  }, [items, query]);

  // Group by category
  const grouped = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {};
    for (const item of filtered) {
      if (!groups[item.category]) groups[item.category] = [];
      groups[item.category].push(item);
    }
    return CATEGORY_ORDER
      .filter((cat) => groups[cat]?.length)
      .map((cat) => ({ category: cat, items: groups[cat] }));
  }, [filtered]);

  // Flat list for keyboard nav
  const flatItems = useMemo(
    () => grouped.flatMap((g) => g.items),
    [grouped],
  );

  // Clamp selected index
  useEffect(() => {
    if (selectedIndex >= flatItems.length) {
      setSelectedIndex(Math.max(0, flatItems.length - 1));
    }
  }, [flatItems.length, selectedIndex]);

  const executeItem = useCallback(
    (item: CommandItem) => {
      onOpenChange(false);
      item.action();
    },
    [onOpenChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, flatItems.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (flatItems[selectedIndex]) {
          executeItem(flatItems[selectedIndex]);
        }
      }
    },
    [flatItems, selectedIndex, executeItem],
  );

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${selectedIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  let flatIndex = -1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-lg">
        {/* Search input */}
        <div className="flex items-center border-b px-3">
          <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <Input
            ref={inputRef}
            className="border-0 bg-transparent shadow-none focus-visible:ring-0"
            placeholder="Type a command or search..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
          />
          <kbd className="ml-2 inline-flex h-5 items-center rounded border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto p-2">
          {flatItems.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              No results found
            </div>
          ) : (
            grouped.map(({ category, items: groupItems }) => (
              <div key={category} className="mb-2">
                <p className="mb-1 px-2 text-xs font-medium text-muted-foreground">
                  {CATEGORY_LABELS[category] || category}
                </p>
                {groupItems.map((item) => {
                  flatIndex++;
                  const idx = flatIndex;
                  return (
                    <button
                      key={item.id}
                      data-index={idx}
                      className={`flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm transition-colors ${
                        idx === selectedIndex
                          ? "bg-accent text-accent-foreground"
                          : "text-foreground hover:bg-accent/50"
                      }`}
                      onClick={() => executeItem(item)}
                      onMouseEnter={() => setSelectedIndex(idx)}
                    >
                      <span className="flex-1">
                        <span className="font-medium">{item.label}</span>
                        {item.description && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            {item.description}
                          </span>
                        )}
                      </span>
                      {item.shortcut && (
                        <kbd className="inline-flex h-5 items-center rounded border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
                          {item.shortcut}
                        </kbd>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t px-3 py-2 text-[10px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1">
              <kbd className="rounded border bg-muted px-1">↑↓</kbd> Navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border bg-muted px-1">↵</kbd> Select
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Command className="h-3 w-3" />
            <span>K to toggle</span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
