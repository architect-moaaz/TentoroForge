import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { formatValue } from "../../utils/formatValue";

type Level = 1 | 2 | 3 | 4 | 5 | 6;
type Weight = "light" | "regular" | "bold" | "display";

type Props = {
  level?: Level;
  content: string;
  id?: string;
  weight?: Weight;
  style?: StyleSlotT;
  /** Optional className override — carries Figma-sourced text-size / color / font
   *  tokens from the schema transformer, e.g. "text-[24px] font-medium". When
   *  present, it is merged AFTER the level-derived class so it wins. */
  className?: string;
};

const TAGS: Record<Level, "h1" | "h2" | "h3" | "h4" | "h5" | "h6"> = {
  1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6",
};

// Use standard Tailwind utilities that always resolve. Earlier attempted
// custom tokens (``text-page-title``, ``text-section-title``, …) required
// matching declarations in globals.css / tokens.custom.css that were never
// emitted, so the browser fell back to default `<h1>`/`<h2>` styles —
// huge font-size + large default margin — producing an "unstructured
// giant heading" block around a single line of text.
const LEVEL_CLASS: Record<Level, string> = {
  1: "text-3xl md:text-4xl font-semibold tracking-tight leading-tight break-words [overflow-wrap:anywhere]",
  2: "text-2xl md:text-3xl font-semibold tracking-tight leading-tight break-words [overflow-wrap:anywhere]",
  3: "text-lg md:text-xl font-semibold leading-snug break-words [overflow-wrap:anywhere]",
  4: "text-base font-semibold leading-snug break-words [overflow-wrap:anywhere]",
  5: "text-sm font-medium break-words [overflow-wrap:anywhere]",
  6: "text-xs font-medium uppercase tracking-wide break-words [overflow-wrap:anywhere]",
};

const WEIGHT_CLASS: Record<Weight, string> = {
  light:   "font-light",
  regular: "font-medium",
  bold:    "font-semibold",
  display: "font-bold tracking-tight",
};

export function Heading({ level = 2, content, id, weight, style, className: extraCn }: Props) {
  const Tag = TAGS[level];
  // When the caller passes an explicit text-[Npx] class (Figma-sourced overrides),
  // omit the semantic level class to avoid a specificity collision. Both classes
  // set font-size; the stylesheet order determines which wins and it's not stable
  // across Tailwind versions. Omitting the level class is safer and produces the
  // intended size directly.
  const hasExplicitTextSize = extraCn ? /\btext-\[\d/.test(extraCn) : false;
  const className = [
    hasExplicitTextSize ? undefined : LEVEL_CLASS[level],
    weight ? WEIGHT_CLASS[weight] : undefined,
    // Figma-sourced overrides (text-[Npx], font-*, tracking-*, color) come last.
    extraCn,
  ].filter(Boolean).join(" ");

  const headingStyle: React.CSSProperties = {
    fontFamily: "var(--font-heading, inherit)",
    fontWeight: "var(--font-heading-weight, inherit)" as React.CSSProperties["fontWeight"],
    letterSpacing: "var(--font-heading-tracking, normal)",
    // User-provided style slot wins — must come after defaults
    ...resolveStyle(style),
  };

  return (
    <Tag
      id={id}
      data-weight={weight}
      className={className}
      style={headingStyle}
      {...useMotion(style?.motion)}
    >
      {/* Coerce through formatValue: a schema binding like {{errors}} that
          resolves to an object would otherwise trigger React error #31
          ("Objects are not valid as a React child") and crash the whole
          page. Root-cause safety net for B-022.4 across every text-position
          component in the library. */}
      {formatValue(content as unknown)}
    </Tag>
  );
}
