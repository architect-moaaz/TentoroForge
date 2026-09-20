/**
 * Tailwind class families, read and written one family at a time.
 *
 * A setting like "Spacing" is one family (`p-*`); setting it replaces the
 * family's class and leaves every other class alone. A breakpoint prefix
 * (`md:`) is a separate slot of the same family, so the base value and the
 * override for a screen size are stored separately and shown as such
 * (CANVAS-004): a change at one screen size never rewrites another.
 */
import type { Breakpoint } from "../types";

export const BREAKPOINTS: { key: Breakpoint; label: string; minWidth: number }[] = [
  { key: "", label: "All screens", minWidth: 0 },
  { key: "sm", label: "Small and up", minWidth: 640 },
  { key: "md", label: "Tablet and up", minWidth: 768 },
  { key: "lg", label: "Desktop and up", minWidth: 1024 },
  { key: "xl", label: "Wide and up", minWidth: 1280 },
];

export interface ClassGroup {
  key: string;
  label: string;
  /** Matches the class without its breakpoint prefix. */
  test: RegExp;
  options?: { value: string; label: string }[];
  /** Setting this family to this value removes the class instead. */
  none?: string;
}

const opt = (pairs: [string, string][]) => pairs.map(([value, label]) => ({ value, label }));

// Order matters: the first family whose test matches claims the class, so the
// narrower text families come before the colour catch-all.
export const CLASS_GROUPS: ClassGroup[] = [
  { key: "display", label: "Display", test: /^(block|inline-block|inline|flex|inline-flex|grid|hidden|contents)$/,
    options: opt([["block", "Shown"], ["flex", "Row or stack"], ["grid", "Grid"], ["hidden", "Hidden"]]) },
  { key: "flexDirection", label: "Direction", test: /^flex-(row|col|row-reverse|col-reverse)$/,
    options: opt([["flex-row", "Side by side"], ["flex-col", "Stacked"]]) },
  { key: "flexWrap", label: "Wrapping", test: /^flex-(wrap|nowrap)$/,
    options: opt([["flex-wrap", "Wrap onto new lines"], ["flex-nowrap", "Keep on one line"]]) },
  { key: "justify", label: "Horizontal alignment", test: /^justify-(start|end|center|between|around|evenly)$/,
    options: opt([["justify-start", "Left"], ["justify-center", "Centre"], ["justify-end", "Right"], ["justify-between", "Spread out"]]) },
  { key: "items", label: "Vertical alignment", test: /^items-(start|end|center|baseline|stretch)$/,
    options: opt([["items-start", "Top"], ["items-center", "Middle"], ["items-end", "Bottom"], ["items-stretch", "Stretch"]]) },
  { key: "gridCols", label: "Columns", test: /^grid-cols-(\d+|none)$/,
    options: opt([["grid-cols-1", "1"], ["grid-cols-2", "2"], ["grid-cols-3", "3"], ["grid-cols-4", "4"]]) },
  { key: "gap", label: "Space between items", test: /^gap-(\d+(\.\d+)?|px)$/,
    options: opt([["gap-1", "Tight"], ["gap-2", "Small"], ["gap-4", "Medium"], ["gap-6", "Large"], ["gap-8", "Extra large"]]) },
  { key: "spaceY", label: "Space between rows", test: /^space-y-(\d+(\.\d+)?|px)$/,
    options: opt([["space-y-1", "Tight"], ["space-y-2", "Small"], ["space-y-4", "Medium"], ["space-y-6", "Large"], ["space-y-8", "Extra large"]]) },
  { key: "padding", label: "Space inside", test: /^p-(\d+(\.\d+)?|px)$/,
    options: opt([["p-0", "None"], ["p-2", "Small"], ["p-4", "Medium"], ["p-6", "Large"], ["p-8", "Extra large"]]), none: "p-0" },
  { key: "paddingX", label: "Space inside (sides)", test: /^px-(\d+(\.\d+)?|px)$/,
    options: opt([["px-0", "None"], ["px-2", "Small"], ["px-4", "Medium"], ["px-6", "Large"], ["px-8", "Extra large"]]) },
  { key: "paddingY", label: "Space inside (top and bottom)", test: /^py-(\d+(\.\d+)?|px)$/,
    options: opt([["py-0", "None"], ["py-2", "Small"], ["py-4", "Medium"], ["py-6", "Large"], ["py-8", "Extra large"]]) },
  { key: "marginTop", label: "Space above", test: /^mt-(\d+(\.\d+)?|px|auto)$/,
    options: opt([["mt-0", "None"], ["mt-2", "Small"], ["mt-4", "Medium"], ["mt-6", "Large"], ["mt-8", "Extra large"]]) },
  { key: "marginBottom", label: "Space below", test: /^mb-(\d+(\.\d+)?|px|auto)$/,
    options: opt([["mb-0", "None"], ["mb-2", "Small"], ["mb-4", "Medium"], ["mb-6", "Large"], ["mb-8", "Extra large"]]) },
  { key: "colSpan", label: "Columns it takes", test: /^col-span-(\d+|full)$/,
    options: opt([["col-span-1", "1"], ["col-span-2", "2"], ["col-span-3", "3"], ["col-span-4", "4"], ["col-span-full", "All"]]) },
  { key: "width", label: "Width", test: /^w-(full|auto|fit|screen|min|max|\d+(\/\d+)?|\[.+\])$/,
    options: opt([["w-auto", "As wide as its content"], ["w-full", "Fill the space"], ["w-1/2", "Half"], ["w-1/3", "A third"]]) },
  { key: "maxWidth", label: "Maximum width", test: /^max-w-(none|xs|sm|md|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|full|prose|screen-\w+|\[.+\])$/,
    options: opt([["max-w-none", "No limit"], ["max-w-md", "Narrow"], ["max-w-2xl", "Medium"], ["max-w-5xl", "Wide"], ["max-w-full", "Full"]]) },
  { key: "height", label: "Height", test: /^h-(full|auto|fit|screen|min|max|\d+(\.\d+)?|px|\[.+\])$/,
    options: opt([["h-auto", "As tall as its content"], ["h-full", "Fill the space"], ["h-2", "Tiny"], ["h-6", "Small"], ["h-12", "Medium"], ["h-24", "Large"]]) },
  { key: "textAlign", label: "Text alignment", test: /^text-(left|center|right|justify)$/,
    options: opt([["text-left", "Left"], ["text-center", "Centre"], ["text-right", "Right"]]) },
  { key: "textSize", label: "Text size", test: /^text-(xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|\[\d+px\])$/,
    options: opt([["text-xs", "Tiny"], ["text-sm", "Small"], ["text-base", "Normal"], ["text-lg", "Large"], ["text-xl", "Larger"], ["text-2xl", "Heading"], ["text-3xl", "Big heading"]]) },
  { key: "fontWeight", label: "Weight", test: /^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/,
    options: opt([["font-normal", "Regular"], ["font-medium", "Medium"], ["font-semibold", "Semibold"], ["font-bold", "Bold"]]) },
  { key: "textColor", label: "Text colour", test: /^text-(?!(xs|sm|base|lg|xl|\dxl|left|center|right|justify)(\/|$))[a-z][\w-]*(\/\d+)?$/,
    options: opt([["text-foreground", "Normal"], ["text-muted-foreground", "Muted"], ["text-primary", "Accent"],
                  ["text-destructive", "Danger"], ["text-primary-foreground", "On accent"]]) },
  { key: "background", label: "Background", test: /^bg-[a-z][\w-]*(\/\d+)?$/,
    options: opt([["bg-transparent", "None"], ["bg-background", "Page"], ["bg-card", "Card"], ["bg-muted", "Muted"],
                  ["bg-primary", "Accent"], ["bg-secondary", "Secondary"], ["bg-destructive", "Danger"]]), none: "bg-transparent" },
  { key: "rounded", label: "Rounded corners", test: /^rounded(-(none|sm|md|lg|xl|2xl|3xl|full))?$/,
    options: opt([["rounded-none", "Square"], ["rounded-md", "Slight"], ["rounded-lg", "Rounded"], ["rounded-xl", "Very rounded"], ["rounded-full", "Pill"]]) },
  { key: "border", label: "Border", test: /^border(-(0|2|4|8))?$/,
    options: opt([["border-0", "None"], ["border", "Thin"], ["border-2", "Thick"]]), none: "border-0" },
  { key: "shadow", label: "Shadow", test: /^shadow(-(none|sm|md|lg|xl|2xl))?$/,
    options: opt([["shadow-none", "None"], ["shadow-sm", "Subtle"], ["shadow", "Soft"], ["shadow-lg", "Strong"]]), none: "shadow-none" },
];

export const GROUP_BY_KEY: Record<string, ClassGroup> = Object.fromEntries(CLASS_GROUPS.map((g) => [g.key, g]));

const BP_RE = /^(sm|md|lg|xl|2xl|hover|focus):(.+)$/;

/** A slot a class family can be set in: a screen size, or a state (hover, focus). */
export type Slot = Breakpoint | "2xl" | "hover" | "focus";

export function splitClass(cls: string): { bp: Slot; base: string } {
  const m = BP_RE.exec(cls);
  return m ? { bp: m[1] as Slot, base: m[2] } : { bp: "", base: cls };
}

export function parseClasses(classes: string | null | undefined): string[] {
  return (classes ?? "").split(/\s+/).filter(Boolean);
}

export function groupOf(cls: string): ClassGroup | null {
  const { base } = splitClass(cls);
  // Other variants (dark:, disabled:, data-[…]) belong to no family we edit.
  if (/^(active|dark|group-hover|disabled|data-\[)/.test(base)) return null;
  return CLASS_GROUPS.find((g) => g.test.test(base)) ?? null;
}

/** The family's value at exactly this breakpoint slot, or null. */
export function getGroupValue(classes: string, group: string, bp: Slot): string | null {
  const g = GROUP_BY_KEY[group];
  if (!g) return null;
  for (const cls of parseClasses(classes)) {
    const s = splitClass(cls);
    if (s.bp === bp && g.test.test(s.base) && groupOf(cls) === g) return s.base;
  }
  return null;
}

/** What actually applies at this breakpoint: the nearest slot at or below it. */
export function effectiveValue(classes: string, group: string, bp: Breakpoint): { value: string | null; from: Breakpoint | null } {
  const order: Breakpoint[] = ["", "sm", "md", "lg", "xl"];
  const upto = order.slice(0, order.indexOf(bp) + 1).reverse();
  for (const slot of upto) {
    const v = getGroupValue(classes, group, slot);
    if (v != null) return { value: v, from: slot };
  }
  return { value: null, from: null };
}

/** Replace the family's class at this slot (null removes it). Every other class stays, in order. */
export function setGroupValue(classes: string, group: string, bp: Slot, value: string | null): string {
  const g = GROUP_BY_KEY[group];
  if (!g) return classes;
  const prefix = bp ? `${bp}:` : "";
  const kept: string[] = [];
  let placed = false;
  for (const cls of parseClasses(classes)) {
    const s = splitClass(cls);
    if (s.bp === bp && groupOf(cls) === g) {
      if (value != null && !placed) { kept.push(prefix + value); placed = true; }
      continue;
    }
    kept.push(cls);
  }
  if (value != null && !placed) kept.push(prefix + value);
  return kept.join(" ");
}

/** The breakpoint a viewport width falls in, as Tailwind resolves it. */
export function breakpointForWidth(width: number): Breakpoint {
  let bp: Breakpoint = "";
  for (const b of BREAKPOINTS) if (width >= b.minWidth) bp = b.key;
  return bp;
}

/** Visibility by screen size, expressed as `hidden` / `md:block` pairs. */
export type Visibility = "all" | "wide-only" | "narrow-only";

export function getVisibility(classes: string): Visibility {
  const base = getGroupValue(classes, "display", "");
  const md = getGroupValue(classes, "display", "md");
  if (base === "hidden" && md && md !== "hidden") return "wide-only";
  if (base !== "hidden" && md === "hidden") return "narrow-only";
  return "all";
}

export function setVisibility(classes: string, visibility: Visibility, shownAs = "block"): string {
  const current = getGroupValue(classes, "display", "");
  const shown = current && current !== "hidden" ? current : shownAs;
  let out = setGroupValue(classes, "display", "md", null);
  if (visibility === "all") return setGroupValue(out, "display", "", current === "hidden" ? null : current);
  if (visibility === "wide-only") {
    out = setGroupValue(out, "display", "", "hidden");
    return setGroupValue(out, "display", "md", shown);
  }
  out = setGroupValue(out, "display", "", shown);
  return setGroupValue(out, "display", "md", "hidden");
}
