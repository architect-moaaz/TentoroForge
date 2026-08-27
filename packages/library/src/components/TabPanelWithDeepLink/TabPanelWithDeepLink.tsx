"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface Props {
  paramKey?: string;
  tabs: Array<{ id: string; label: string }>;
  defaultTab?: string;
  children?: React.ReactNode;
}

export function TabPanelWithDeepLink({
  paramKey = "tab", tabs, defaultTab, children,
}: Props) {
  const fallback = defaultTab ?? tabs[0]?.id ?? "";
  const [activeTab, setActiveTab] = useUrlState(paramKey, fallback);
  const childArray = React.Children.toArray(children);

  const activeIndex = Math.max(0, tabs.findIndex((t) => t.id === activeTab));
  const activeContent = childArray[activeIndex] ?? null;

  return (
    <div className="flex flex-col">
      <div role="tablist" className="flex items-center gap-1 border-b border-border">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab.id)}
              className={`relative px-4 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
              {isActive && (
                <span className="absolute -bottom-px left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="flex-1 pt-4">
        {activeContent}
      </div>
    </div>
  );
}
