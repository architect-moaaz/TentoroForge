/**
 * The space around and inside a part of a phone screen: a margin and a padding on each side, read from and written to the part's own `style`.
 *
 * Only a plain object of numbers is read as margins (`{ marginTop: 16, paddingLeft: 8 }`). Whatever else the part's style holds (a colour, a size)
 * is kept exactly as written; a style that is not a plain object, or a margin that is not a number, is the screen's own code
 * and is shown, not changed.
 */
import type { Op, PhonePart } from "./types";

/** The kit's parts that take a `style`. */
export const STYLE_PARTS: ReadonlySet<string> = new Set(["Stack", "Row", "Card", "Divider", "Text", "Button", "GradientBand", "ListView"]);

export const KINDS = [{ kind: "margin", label: "Margin" }, { kind: "padding", label: "Padding" }] as const;
export type SpaceKind = (typeof KINDS)[number]["kind"];

export const SIDE_NAMES = [
  { side: "Top", label: "Top" },
  { side: "Right", label: "Right" },
  { side: "Bottom", label: "Bottom" },
  { side: "Left", label: "Left" },
] as const;

/** Every style key this reads and writes: marginTop ... paddingLeft, margins first. */
export const SIDES = KINDS.flatMap((k) => SIDE_NAMES.map((s) => ({ key: `${k.kind}${s.side}` as `${SpaceKind}${(typeof SIDE_NAMES)[number]["side"]}`, kind: k.kind, label: s.label })));
export type SideKey = (typeof SIDES)[number]["key"];
export type Margins = Partial<Record<SideKey, number>>;

/** The design system's spacing steps, in points. */
export const SIZES = [
  { name: "xs", value: 4 },
  { name: "sm", value: 8 },
  { name: "md", value: 16 },
  { name: "lg", value: 24 },
  { name: "xl", value: 32 },
  { name: "xxl", value: 48 },
] as const;

export interface Space {
  margins: Margins;
  /** The other entries of the style, as written. */
  rest: string[];
  /** The screen's own code decides this style: shown, not changed from here. */
  fromCode: boolean;
}

/** `a, b: {c, d}, e` split at the commas that are not inside brackets or quotes. */
function entriesOf(inner: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let quote = "";
  let from = 0;
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === "," && depth === 0) {
      out.push(inner.slice(from, i));
      from = i + 1;
    }
  }
  out.push(inner.slice(from));
  return out.map((e) => e.trim()).filter(Boolean);
}

export function readSpace(part: PhonePart): Space {
  const style = part.props.find((p) => p.name === "style");
  if (!style) return { margins: {}, rest: [], fromCode: false };
  const code = String(style.value ?? "").trim();
  if (style.kind !== "expr" || !code.startsWith("{") || !code.endsWith("}")) return { margins: {}, rest: [], fromCode: true };
  const margins: Margins = {};
  const rest: string[] = [];
  for (const entry of entriesOf(code.slice(1, -1))) {
    const m = /^((?:margin|padding)(?:Top|Right|Bottom|Left))\s*:\s*(.+)$/.exec(entry);
    if (!m) {
      rest.push(entry);
      continue;
    }
    if (!/^-?\d+(\.\d+)?$/.test(m[2].trim())) return { margins: {}, rest: [], fromCode: true };
    margins[m[1] as SideKey] = Number(m[2]);
  }
  return { margins, rest, fromCode: false };
}

/** The change that gives a part these margins and keeps the rest of its style. A side left out has none. */
export function spaceOp(part: PhonePart, margins: Margins, rest: string[]): Op {
  const own = SIDES.filter((s) => margins[s.key] !== undefined).map((s) => `${s.key}: ${margins[s.key]}`);
  const entries = [...rest, ...own];
  return { op: "setProp", id: part.id, name: "style", value: { kind: "expr", value: entries.length ? `{ ${entries.join(", ")} }` : "{}" } };
}

/** What was typed in a side's box: nothing is no margin; a number is that many points; anything else is not a margin. */
export function marginOf(text: string): number | undefined | "bad" {
  const t = text.trim();
  if (t === "") return undefined;
  if (!/^-?\d{1,3}(\.\d+)?$/.test(t)) return "bad";
  return Number(t);
}

/** The step a number is, or null when it is between steps. */
export function sizeNamed(value: number | undefined): string | null {
  return SIZES.find((s) => s.value === value)?.name ?? null;
}
