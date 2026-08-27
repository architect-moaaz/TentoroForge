"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TabsPropsType } from "./Tabs.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";

/**
 * Tabs — indexed-children tab container. children[i] is the panel for
 * tabs[i]. Optional onChange callback for controlled use; without it Tabs
 * maintains its own internal state and the schema's `value` is just the
 * initial value. Renders with shadcn-style underlined-tabs chrome.
 */
export interface TabsProps extends TabsPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
  /** Optional controlled-mode change handler. When omitted, Tabs is uncontrolled. */
  onChange?: (value: string) => void;
}

const TAB_STRIP_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "gap-1",
  comfortable: "gap-0",
  spacious:    "gap-4",
};

const TAB_BASE =
  "inline-flex items-center justify-center px-4 h-10 -mb-px text-sm font-medium " +
  "text-muted-foreground hover:text-foreground transition-colors border-b-2 " +
  "border-transparent focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring focus-visible:ring-offset-2";
const TAB_ACTIVE = "text-foreground border-primary";

export function Tabs({ tabs, value, style, children, onChange }: TabsProps) {
  const [internalValue, setInternalValue] = React.useState(value);
  const active = onChange ? value : internalValue;
  const density = useDensity();

  function handleSelect(id: string) {
    if (onChange) onChange(id);
    else setInternalValue(id);
  }

  const panels = React.Children.toArray(children);

  return (
    <div className="w-full" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <div
        className={`flex flex-wrap items-center border-b border-border ${TAB_STRIP_GAP[density]}`}
        role="tablist"
      >
        {tabs.map((t) => {
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              className={`${TAB_BASE} ${isActive ? TAB_ACTIVE : ""}`}
              data-tab-id={t.id}
              data-tab-active={isActive ? "true" : "false"}
              role="tab"
              aria-selected={isActive}
              type="button"
              onClick={() => handleSelect(t.id ?? t.label)}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="pt-4">
        {tabs.map((t, i) => (
          <div
            key={t.id}
            className="focus:outline-none"
            data-tab-panel={t.id}
            data-tab-active={active === t.id ? "true" : "false"}
            role="tabpanel"
            hidden={active !== t.id}
          >
            {panels[i]}
          </div>
        ))}
      </div>
    </div>
  );
}
