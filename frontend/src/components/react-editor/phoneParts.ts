/**
 * Finding, in a phone screen's code, the part a person clicked in the picture.
 *
 * The picture marks each part with the file and line of the code that drew it (`source`: where the bridge got it). The editor's
 * model of a screen lists its parts with the line each starts on, so the click names the part. Pure functions: what to show and
 * what to ask of the server for it is decided here, where it can be tested without a phone.
 */
import type { Op, PhonePart } from "./types";

export interface Source { file: string; line: number; component: string | null }

/** `src/screens/PAGE-001.tsx` is a screen's own file, `src/screens/PAGE-001/<key>.tsx` one of its parts. Anything else (a route
 *  file that hands over to a screen, the kit) is not a screen the person can edit here. */
export function screenOf(file: string | null | undefined): { page: string; part: string | null } | null {
  const m = /(?:^|\/)src\/screens\/(PAGE-[\w-]+?)(?:\/([\w-]+))?\.tsx$/.exec((file ?? "").replace(/\\/g, "/"));
  return m ? { page: m[1], part: m[2] ?? null } : null;
}

/** The part of the screen that the click names: the one of that kind that starts on that line, in that file. */
export function findPart(nodes: Record<string, PhonePart>, source: Source | null): PhonePart | null {
  const where = screenOf(source?.file);
  if (!where || !source) return null;
  const file = where.part ? `part:${where.part}` : "view";
  const here = Object.values(nodes).filter((n) => (n.file ?? "view") === file && n.kind !== "fragment");
  const same = (n: PhonePart) => !source.component || n.type === source.component;
  return here.find((n) => n.line === source.line && same(n)) ?? null;
}

export interface Field {
  /** What it changes: the words between the tags, or a setting of the part. */
  kind: "text" | "prop";
  name: string;
  label: string;
  value: string;
}

const LABELS: Record<string, string> = {
  title: "Title", label: "Label", placeholder: "Hint inside the box", message: "Message", subtitle: "Subtitle",
  description: "Description", heading: "Heading", caption: "Caption", text: "Text", hint: "Hint", helper: "Helper text",
};

/** What can be typed over on a part: its words, and the settings that hold words. Words that come from data cannot. */
export function fieldsOf(part: PhonePart, words: string[]): Field[] {
  const out: Field[] = [];
  if (part.textEditable && typeof part.text === "string" && part.text.trim() !== "") {
    out.push({ kind: "text", name: "", label: "Words", value: part.text.trim() });
  }
  for (const p of part.props) {
    if (p.kind === "string" && words.includes(p.name) && typeof p.value === "string") {
      out.push({ kind: "prop", name: p.name, label: LABELS[p.name] ?? p.name, value: p.value });
    }
  }
  return out;
}

export function opFor(part: PhonePart, field: Field, value: string): Op {
  return field.kind === "text"
    ? { op: "setText", id: part.id, text: value }
    : { op: "setProp", id: part.id, name: field.name, value: { kind: "string", value } };
}

/** A part that cannot be copied or taken away from here: the screen itself, or a part its parent holds as a setting. */
export function isScreenRoot(part: PhonePart): boolean {
  return part.parent == null || !!part.slot;
}
