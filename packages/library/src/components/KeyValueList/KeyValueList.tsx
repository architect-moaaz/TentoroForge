"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { KeyValueListPropsType } from "./KeyValueList.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";
import { formatValue } from "../../utils/formatValue";
import { SCROLL_X } from "../../style/scroll";

/**
 * KeyValueList — definition-list display. Empty values render as em-dash
 * placeholder. `copyable` items get a small copy-to-clipboard button next
 * to the value. Renders with shadcn/Tailwind utilities so the project's
 * globals.css governs the look.
 *
 * Wave 2: density drives row vertical spacing.
 * "comfortable" (default) matches today's py-2.5 gap-1 sm:gap-4 exactly.
 */

// density → row gap + vertical padding classes.
// "comfortable" matches today's appearance exactly.
const DENSITY_ROW: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "gap-1 sm:gap-3 py-1.5",
  comfortable: "gap-1 sm:gap-4 py-2.5",  // today's default
  spacious:    "gap-1 sm:gap-6 py-4",
};

export interface KeyValueListProps extends KeyValueListPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function KeyValueList({ items, style }: KeyValueListProps) {
  const density = useDensity();
  const rowCls = DENSITY_ROW[density];

  return (
    <dl
      className={`flex flex-col divide-y divide-border ${SCROLL_X}`}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {items.map((item, i) => {
        // A bound value may be a Date/number/null the schema didn't predict —
        // coerce so rendering (and clipboard) never crash on a non-string child.
        const display = formatValue(item.value);
        const isEmpty = display === "";
        const handleCopy = () => {
          if (typeof navigator !== "undefined" && navigator.clipboard) {
            navigator.clipboard.writeText(display).catch(() => { /* ignore */ });
          }
        };
        return (
          <div
            key={i}
            className={`grid grid-cols-1 sm:grid-cols-[minmax(0,160px)_1fr] ${rowCls}`}
            data-kv-row=""
          >
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {item.label}
            </dt>
            <dd
              className={`text-sm flex items-center gap-2 min-w-0 break-words ${isEmpty ? "text-muted-foreground/60 italic" : "text-foreground"}`}
              data-kv-empty={isEmpty || undefined}
            >
              <span>{isEmpty ? "—" : display}</span>
              {item.copyable && !isEmpty && (
                <button
                  type="button"
                  className="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  aria-label={`Copy ${item.label}`}
                  onClick={handleCopy}
                >
                  ⧉
                </button>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
