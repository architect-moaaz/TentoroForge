"use client";

/**
 * The project page's tabs, across the top: Smith and the four views of what
 * the app is made of — Data Model, Editor, Workflows, Agents — and the rest
 * behind "More", the everyday tools (Files, Versions, Preview, Settings) first.
 */
import { useState } from "react";
import {
  Bot, ChevronDown, Code, Database, Eye, GitBranch, Layout, MessageSquare, Route, Scale, Settings, Shield, Workflow,
} from "lucide-react";

import { LockBadge } from "@/components/features/Locked";
import type { FeatureKey } from "@/lib/features";

export type Tab = "chat" | "preview" | "code" | "data" | "rules" | "business-rules" | "decisions" | "workflows" | "editor" | "schema-editor" | "design" | "design-editor" | "ir-editor" | "navigation" | "app-flow" | "agents" | "ai" | "monitoring" | "versions" | "office" | "app-settings";

export type TabSpec = { id: Tab; label: string; icon: React.ComponentType<{ className?: string }>; shortcut?: string; feature?: FeatureKey };

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
  { id: "code", label: "Files", icon: Code, shortcut: "⌘3", feature: "code_view" },
  { id: "versions", label: "Versions", icon: GitBranch },
  { id: "preview", label: "Preview", icon: Eye, shortcut: "⌘2" },
  { id: "app-settings", label: "Settings", icon: Settings },
  { id: "rules", label: "Rules", icon: Shield },
  { id: "business-rules", label: "Business Rules", icon: Scale },
  // ONE MAP OF THE APP: Pages & Nav and App Flow each drew half of it.
  { id: "app-flow", label: "App Map", icon: Route },
];

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
          ? `flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-slate-50 dark:hover:bg-slate-800 ${current ? "text-brand-900 font-medium dark:text-white" : "text-slate-700 dark:text-slate-200"}`
          : `relative flex h-11 items-center gap-1.5 px-1 text-[13px] transition-colors ${
              current ? "font-medium text-brand-900 dark:text-white"
                      : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}
      >
        <Icon className="h-4 w-4" />
        {t.label}
        {locked && <LockBadge />}
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
            <div className="absolute left-0 z-20 mt-1 w-52 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
              {more.map((t) => tab(t, true))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
