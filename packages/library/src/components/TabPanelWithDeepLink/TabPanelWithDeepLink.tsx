"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface Props {
  paramKey?: string;
  tabs?: Array<{ id?: string; label?: string }>;
  defaultTab?: string;
  children?: React.ReactNode;
}

/**
 * The tab strip is derived from the CHILDREN, with `tabs[i]` supplying the id
 * and label when it has them.
 *
 * `tabs` defaults to `null` in the registry and its only control is
 * `actionPicker`, which cannot author an array of `{id,label}` — so a dropped
 * TabPanelWithDeepLink rendered an empty `role="tablist"` with no buttons at
 * all, and every child after the first was unreachable because nothing could
 * ever set the URL param to its id (docs/editor-audit/containment.md:
 * "inherits the same one-panel-only defect" as Tabs). One tab per child means
 * the component works from drag-and-drop alone; declared tabs still win, so
 * schemas that already carry a real array render identically.
 */
function readChildProp(child: unknown, key: "label" | "value", depth = 0): string | undefined {
  if (depth > 4 || !React.isValidElement(child)) return undefined;
  const p = (child.props ?? {}) as Record<string, any>;
  if (typeof p[key] === "string" && p[key]) return p[key];
  if (p.validatedProps && typeof p.validatedProps[key] === "string" && p.validatedProps[key]) {
    return p.validatedProps[key];
  }
  if (p.node?.props && typeof p.node.props[key] === "string" && p.node.props[key]) {
    return p.node.props[key];
  }
  return readChildProp(p.children, key, depth + 1);
}

export function TabPanelWithDeepLink({
  paramKey = "tab", tabs, defaultTab, children,
}: Props) {
  const childArray = React.Children.toArray(children);
  const declared = Array.isArray(tabs) ? tabs : [];
  const defs = Array.from(
    { length: Math.max(declared.length, childArray.length) },
    (_, i) => ({
      id: declared[i]?.id || readChildProp(childArray[i], "value") || `tab-${i}`,
      label: declared[i]?.label || readChildProp(childArray[i], "label") || `Tab ${i + 1}`,
    }),
  );

  const fallback = defaultTab || defs[0]?.id || "";
  const [activeTab, setActiveTab] = useUrlState(paramKey, fallback);

  const activeIndex = Math.max(0, defs.findIndex((t) => t.id === activeTab));
  const activeContent = childArray[activeIndex] ?? null;

  return (
    <div className="flex flex-col">
      <div role="tablist" className="flex items-center gap-1 border-b border-border">
        {defs.map((tab) => {
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
                <span className="absolute -bottom-px start-0 end-0 h-0.5 bg-primary" />
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
