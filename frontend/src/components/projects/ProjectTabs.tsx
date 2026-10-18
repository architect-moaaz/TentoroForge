"use client";

/**
 * The project page's tabs, across the top: Smith and the four views of what
 * the app is made of — Data Model, Editor, Workflows, Agents — and the rest
 * behind "More", grouped by what they are for: trying and shipping the app,
 * how it works, and the project itself — each with a line saying what it is.
 */
import { useState } from "react";
import {
  Bot, ChevronDown, Code, Database, Eye, GitBranch, Layout, MessageSquare, Route, Scale, Settings, Shield, Workflow,
} from "lucide-react";

import { LockBadge } from "@/components/features/Locked";
import type { FeatureKey } from "@/lib/features";

export type Tab = "chat" | "preview" | "code" | "data" | "rules" | "business-rules" | "decisions" | "workflows" | "editor" | "schema-editor" | "design" | "design-editor" | "ir-editor" | "navigation" | "app-flow" | "agents" | "ai" | "monitoring" | "versions" | "office" | "app-settings";

export type TabSpec = {
  id: Tab; label: string; icon: React.ComponentType<{ className?: string }>; shortcut?: string; feature?: FeatureKey;
  /** In the More menu: the heading it sits under, and what it is for in a few words. */
  group?: MoreGroup; hint?: string;
};

/** The More menu's headings, in order. */
export const MORE_GROUPS = ["Try and ship", "How it works", "Project"] as const;
export type MoreGroup = (typeof MORE_GROUPS)[number];

// THE FIVE ACROSS THE TOP — Smith and the four views of what the app is
// made of — AND THE REST BEHIND "MORE", the tools first.
export const PRIMARY_TABS: TabSpec[] = [
  { id: "chat", label: "Smith", icon: MessageSquare, shortcut: "⌘1" },
  { id: "data", label: "Data Model", icon: Database },
  { id: "editor", label: "Editor", icon: Layout },
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "agents", label: "Agents", icon: Bot, feature: "agents" },
];
export const MORE_TABS: TabSpec[] = [
  { id: "preview", label: "Preview", icon: Eye, shortcut: "⌘2", group: "Try and ship", hint: "Use the app as its people will" },
  { id: "versions", label: "Versions", icon: GitBranch, group: "Try and ship", hint: "Every change and publish, and going back" },
  // ONE MAP OF THE APP: Pages & Nav and App Flow each drew half of it.
  { id: "app-flow", label: "App Map", icon: Route, group: "How it works", hint: "Every screen and the paths through them" },
  { id: "business-rules", label: "Business Rules", icon: Scale, group: "How it works", hint: "What the app checks and works out" },
  { id: "rules", label: "Access & Rules", icon: Shield, group: "How it works", hint: "Who may see and do what" },
  { id: "code", label: "Files", icon: Code, shortcut: "⌘3", feature: "code_view", group: "Project", hint: "The app's source files" },
  { id: "app-settings", label: "Settings", icon: Settings, group: "Project", hint: "Name, addresses, sign-in and more" },
];

/** The More items under their headings, in the headings' order; anything
 *  without a heading comes last, under none. */
export function groupsOf(more: TabSpec[]): { group: MoreGroup | ""; items: TabSpec[] }[] {
  const out: { group: MoreGroup | ""; items: TabSpec[] }[] = MORE_GROUPS.map((g) => ({ group: g, items: more.filter((t) => t.group === g) }));
  out.push({ group: "", items: more.filter((t) => !t.group) });
  return out.filter((g) => g.items.length > 0);
}

export function TabRow({ tabs, more, active, onPick, allowed }: {
  tabs: TabSpec[]; more: TabSpec[]; active: Tab; onPick: (t: Tab) => void; allowed: (f?: FeatureKey) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const activeMore = more.find((t) => t.id === active);
  const tab = (t: TabSpec, inMenu = false) => {
    const locked = !allowed(t.feature);
    const Icon = t.icon;
    const current = active === t.id;
    return (
      <button
        key={t.id}
        onClick={() => { setOpen(false); onPick(t.id); }}
        aria-current={current ? "page" : undefined}
        data-locked={locked ? t.feature : undefined}
        className={inMenu
          ? `flex w-full items-start gap-2.5 px-3 py-1.5 text-left text-[13px] hover:bg-slate-50 dark:hover:bg-slate-800 ${current ? "bg-slate-50 text-brand-900 dark:bg-slate-800 dark:text-white" : "text-slate-700 dark:text-slate-200"}`
          : `relative flex h-11 items-center gap-1.5 px-1 text-[13px] transition-colors ${
              current ? "font-medium text-brand-900 dark:text-white"
                      : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
      >
        <Icon className={inMenu ? "mt-0.5 h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400" : "h-4 w-4"} />
        {inMenu ? (
          <span className="min-w-0 flex-1">
            <span className={`flex items-center gap-1.5 ${current ? "font-medium" : ""}`}>{t.label}{locked && <LockBadge />}</span>
            {t.hint && <span className="block text-[11.5px] leading-snug text-slate-500 dark:text-slate-400">{t.hint}</span>}
          </span>
        ) : (
          <>{t.label}{locked && <LockBadge />}</>
        )}
        {inMenu && t.shortcut && <kbd className="mt-0.5 shrink-0 font-sans text-[10.5px] text-slate-400">{t.shortcut}</kbd>}
        {current && !inMenu && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand-900 dark:bg-white" />}
      </button>
    );
  };
  return (
    <div className="flex shrink-0 items-center gap-5 border-b border-slate-200/80 bg-white px-5 dark:border-slate-800 dark:bg-slate-900">
      {tabs.map((t) => tab(t))}
      <div className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={`relative flex h-11 items-center gap-1 px-1 text-[13px] ${
            activeMore ? "font-medium text-brand-900 dark:text-white" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
        >
          {activeMore ? activeMore.label : "More"}
          <ChevronDown className="h-3.5 w-3.5" />
          {activeMore && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand-900 dark:bg-white" />}
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
            <div role="menu" className="absolute left-0 z-20 mt-1 w-72 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
              {groupsOf(more).map(({ group, items }, i) => (
                <div key={group || i} data-more-group={group || undefined}
                     className={i > 0 ? "mt-1 border-t border-slate-100 pt-1 dark:border-slate-800" : ""}>
                  {group && (
                    <div className="px-3 pb-0.5 pt-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">{group}</div>
                  )}
                  {items.map((t) => tab(t, true))}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
