/**
 * Finding, in a phone screen's code, the part a person clicked in the picture.
 *
 * The picture marks each part with the file and line of the code that drew it (`source`: where the bridge got it). The editor's
 * model of a screen lists its parts with the line each starts on, so the click names the part. Pure functions: what to show and
 * what to ask of the server for it is decided here, where it can be tested without a phone.
 */
import type { GuideKind, GuideRefs, Op, PalettePart, PhoneKit, PhonePart } from "./types";

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

// ---------------------------------------------------------------------------
// The look: the kit's pick lists
// ---------------------------------------------------------------------------

/** The kit's name for a part: a screen may take `Screen as ScreenView`, and the kit knows it as `Screen`. */
export function kitNameOf(part: PhonePart, imports: Record<string, string>): string | null {
  return imports[part.type] ?? null;
}

const SETTING_LABELS: Record<string, string> = {
  variant: "Style", tone: "Colour", size: "Size", gap: "Space between", padding: "Padding around", align: "Line up", justify: "Spread",
  weight: "Boldness", flex: "Take the free room", wrap: "Wrap onto new lines", fullWidth: "Full width", kind: "Kind", icon: "Icon",
  name: "Icon", dot: "Dot before", type: "Kind", scroll: "Scrolls", padded: "Padded", back: "Back arrow", bleed: "To the edges",
};

const VALUE_LABELS: Record<string, string> = {
  xs: "Extra small", sm: "Small", md: "Medium", lg: "Large", xl: "Extra large", xxl: "Huge",
  start: "Start", end: "End", center: "Centre", stretch: "Stretch", between: "Apart", around: "Around", baseline: "Baseline",
};

export function settingLabel(name: string): string {
  return SETTING_LABELS[name] ?? name.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}

export function valueLabel(value: string): string {
  return VALUE_LABELS[value] ?? value.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export interface Choice {
  name: string;
  label: string;
  kind: "enum" | "boolean";
  values: string[];
  /** The long list this one reads from (the icons). */
  list?: string;
  /** What the part has now: a word, on or off, or nothing (it uses the kit's own default). */
  current: string | boolean | null;
  /** The screen's own code decides this setting (an expression): shown, not changed from here. */
  fromCode: boolean;
  /** Taking it away puts the kit's default back; a setting the kit requires cannot be taken away. */
  optional: boolean;
}

/** What a person can choose on a part: the settings the kit gives it, with what they are now. */
export function choicesOf(part: PhonePart, kit: PhoneKit | null, imports: Record<string, string>): Choice[] {
  const name = kitNameOf(part, imports);
  const settings = (name && kit?.ok ? kit.components[name]?.props : null) ?? {};
  const out: Choice[] = [];
  for (const [prop, spec] of Object.entries(settings)) {
    const has = part.props.find((p) => p.name === prop);
    let current: string | boolean | null = null;
    let fromCode = false;
    if (has) {
      if (spec.kind === "enum") {
        if (has.kind === "string" && typeof has.value === "string") current = has.value;
        else fromCode = true;
      } else if (has.kind === "true") current = true;
      else if (has.kind === "expr" && (has.value === "true" || has.value === "false")) current = has.value === "true";
      else fromCode = true;
    }
    out.push({ name: prop, label: settingLabel(prop), kind: spec.kind, values: spec.values ?? [], list: spec.list, current, fromCode,
               optional: spec.optional !== false });
  }
  return out;
}

/** The change that makes a choice. `null` takes the setting away; the part is then drawn with the kit's own default. */
export function choiceOp(part: PhonePart, choice: Choice, value: string | boolean | null): Op {
  const v = value === null || value === false ? null : value === true ? { kind: "true" as const } : { kind: "string" as const, value };
  return { op: "setProp", id: part.id, name: choice.name, value: v };
}

// ---------------------------------------------------------------------------
// Another order
// ---------------------------------------------------------------------------

function brothers(nodes: Record<string, PhonePart>, part: PhonePart): string[] | null {
  if (part.parent == null || part.slot) return null;
  return nodes[part.parent]?.children ?? null;
}

/** A part one place up (-1) or down (+1) among its brothers; null when it is already at that end or cannot move. */
export function stepOp(nodes: Record<string, PhonePart>, part: PhonePart, step: -1 | 1): Op | null {
  const sibs = brothers(nodes, part);
  if (!sibs || part.parent == null) return null;
  const at = sibs.indexOf(part.id);
  const to = at + step;
  if (at < 0 || to < 0 || to >= sibs.length) return null;
  // The destination is counted before the part is lifted out: one place down is in front of the brother after the next.
  return { op: "move", id: part.id, parentId: part.parent, index: step < 0 ? at - 1 : at + 2 };
}

/** A part dropped before or after another. Only among brothers; null when it would stay where it is. */
export function dropOp(nodes: Record<string, PhonePart>, dragId: string, overId: string, where: "before" | "after"): Op | null {
  const drag = nodes[dragId];
  const over = nodes[overId];
  if (!drag || !over || dragId === overId || drag.parent == null || drag.parent !== over.parent) return null;
  const sibs = brothers(nodes, drag);
  if (!sibs || over.slot) return null;
  const from = sibs.indexOf(dragId);
  const target = sibs.indexOf(overId);
  if (from < 0 || target < 0) return null;
  const index = where === "before" ? target : target + 1;
  if (index === from || index === from + 1) return null;
  return { op: "move", id: dragId, parentId: drag.parent, index };
}

// ---------------------------------------------------------------------------
// Adding a ready part
// ---------------------------------------------------------------------------

export interface Place {
  op: { parentId: string } | { afterId: string } | { beforeId: string };
  /** In words: where the part will go. */
  says: string;
}

/** Where an addition goes: inside the selected part if it can hold others, else after it, else at the end of the screen. */
export function placeFor(nodes: Record<string, PhonePart>, imports: Record<string, string>, containers: string[],
                         selected: PhonePart | null): Place | null {
  const holds = (p: PhonePart) => containers.includes(kitNameOf(p, imports) ?? "");
  if (selected && holds(selected)) return { op: { parentId: selected.id }, says: `inside the selected ${selected.type}` };
  if (selected && selected.parent != null && !selected.slot) return { op: { afterId: selected.id }, says: `after the selected ${selected.type}` };
  const root = Object.values(nodes).find((n) => n.parent == null && holds(n));
  return root ? { op: { parentId: root.id }, says: "at the end of the screen" } : null;
}

/** The three parts that ask a question first and are connected to the application's own workflows and data. They are not in the kit's
 *  list: what they connect to is this application's, so the dialog asks. */
export const GUIDED_PARTS: PalettePart[] = [
  { id: "guided-form", label: "Form that saves", category: "Connected", description: "A form that runs one of the application's workflows",
    search: ["workflow", "save", "submit", "create", "input"], jsx: "", imports: [], container: false, drawnOnly: false, guided: "form" },
  { id: "guided-button", label: "Button that runs a workflow", category: "Connected", description: "A button that runs one of the application's workflows",
    search: ["workflow", "action", "delete", "approve", "press"], jsx: "", imports: [], container: false, drawnOnly: false, guided: "button" },
  { id: "guided-list", label: "List of records", category: "Connected", description: "A list with a row for each record of one kind",
    search: ["table", "rows", "data", "records", "show"], jsx: "", imports: [], container: false, drawnOnly: false, guided: "list" },
];

/** What the row is called where a part is added, when it is added inside a list row: the record a button acts on. */
export function rowVarAt(nodes: Record<string, PhonePart>, holderId: string | null): string | null {
  let here: PhonePart | undefined = holderId ? nodes[holderId] : undefined;
  for (let i = 0; here && i < 100; i++) {
    if (here.rowVar) return here.rowVar;
    here = here.parent ? nodes[here.parent] : undefined;
  }
  return null;
}

/** The part a place adds into: the named one, or the parent of the brother it goes beside. */
export function holderIdOf(nodes: Record<string, PhonePart>, place: Place): string | null {
  if ("parentId" in place.op) return place.op.parentId;
  const ref = nodes["beforeId" in place.op ? place.op.beforeId : place.op.afterId];
  return ref?.parent ?? null;
}

export type Zone = "before" | "inside" | "after";

/** How far down a part the pointer is (0 at its top, 1 at its bottom) as where it means: a part that can hold others is dropped
 *  into when the pointer is in its middle, and beside it near either edge; one that cannot is only dropped before or after. */
export function zoneAt(rel: number, canHold: boolean): Zone {
  if (canHold) return rel < 0.25 ? "before" : rel > 0.75 ? "after" : "inside";
  return rel < 0.5 ? "before" : "after";
}

/** Where a part dropped on another goes. Null when that part has no place for it: the screen itself has no 'beside', and a part
 *  held by a setting (the footer) can be dropped into but not beside. */
export function dropPlace(nodes: Record<string, PhonePart>, imports: Record<string, string>, containers: string[],
                          target: PhonePart, zone: Zone): Place | null {
  const holds = containers.includes(kitNameOf(target, imports) ?? "");
  if (zone === "inside" || target.parent == null || target.slot) {
    return holds ? { op: { parentId: target.id }, says: `inside the ${target.type}` } : null;
  }
  const parent = nodes[target.parent];
  if (!parent || !containers.includes(kitNameOf(parent, imports) ?? "")) return null;
  return zone === "before"
    ? { op: { beforeId: target.id }, says: `before the ${target.type}` }
    : { op: { afterId: target.id }, says: `after the ${target.type}` };
}

/** What a drop on the picture means: the part to add and where it goes, or why it cannot be added. The part comes from the drag
 *  itself (`partId`); `dragging` is only the editor's own record of it, which is cleared when a drag ends, before the picture's
 *  message about the drop arrives. */
export function resolveDrop(args: {
  nodes: Record<string, PhonePart> | null; imports: Record<string, string>; kit: PhoneKit | null; dragging: PalettePart | null;
  partId?: string; source: Source | null; rel: number;
}): { part: PalettePart; place: Place } | { why: string } {
  const { nodes, imports, kit, dragging, partId, source, rel } = args;
  const part = (partId ? [...GUIDED_PARTS, ...(kit?.palette ?? [])].find((p) => p.id === partId) : null) ?? dragging;
  if (!part) return { why: "That was not a part from the Add list." };
  if (!nodes || !kit) return { why: "The screen is still being read. Try again in a moment." };
  if (!source || !screenOf(source.file)) return { why: "That is drawn by the app itself (the tab bar, a menu). Drop it on a part of the screen." };
  const target = findPart(nodes, source);
  if (!target) return { why: "That part could not be found in the screen's code. Redraw the screen and try again." };
  const hold = kit.containers.includes(kitNameOf(target, imports) ?? "");
  const place = dropPlace(nodes, imports, kit.containers, target, zoneAt(rel, hold));
  if (!place) return { why: `A part can't go beside or inside a ${target.type} here. Drop it on the screen itself, or on a box, a column or a row.` };
  return { part, place };
}

/** The part that was just added, in the screen as it is after the change. A part is named by its place (`<parent>.<position>`), so
 *  the new one is the child at the position the addition chose: the end of its parent, or in front of or behind a brother. */
export function newPartAfterAdd(before: Record<string, PhonePart>, place: Place, after: Record<string, PhonePart>): PhonePart | null {
  let id: string | null = null;
  if ("parentId" in place.op) {
    const parent = before[place.op.parentId];
    if (parent) id = `${place.op.parentId}.${parent.children?.length ?? 0}`;
  } else {
    const brother = before["beforeId" in place.op ? place.op.beforeId : place.op.afterId];
    const at = brother?.parent != null ? (before[brother.parent]?.children ?? []).indexOf(brother.id) : -1;
    if (brother?.parent != null && at >= 0) id = `${brother.parent}.${at + ("afterId" in place.op ? 1 : 0)}`;
  }
  return id ? after[id] ?? null : null;
}

/** The changes that add a part: its imports from the kit, then the part. */
export function addOps(part: PalettePart, place: Place): Op[] {
  return [{ op: "addImport", source: "@/ui", names: part.imports }, { op: "insert", jsx: part.jsx, ...place.op }];
}

/** The palette, narrowed by what was typed: by name, description, group or the words people search by. */
export function searchPalette(palette: PalettePart[], text: string): PalettePart[] {
  const needle = text.trim().toLowerCase();
  if (!needle) return palette;
  return palette.filter((p) => [p.label, p.description, p.category, ...p.search].some((s) => s.toLowerCase().includes(needle)));
}

// ---------------------------------------------------------------------------
// The outline
// ---------------------------------------------------------------------------

export interface OutlineRow {
  part: PhonePart;
  depth: number;
}

/** The screen's parts as an indented list, in the order they are written; a part held as a setting follows its owner. */
export function outlineOf(nodes: Record<string, PhonePart>): OutlineRow[] {
  const held = new Map<string, PhonePart[]>();
  for (const n of Object.values(nodes)) {
    if (n.slot && n.parent) held.set(n.parent, [...(held.get(n.parent) ?? []), n]);
  }
  const out: OutlineRow[] = [];
  const walk = (id: string, depth: number) => {
    const part = nodes[id];
    if (!part) return;
    out.push({ part, depth });
    for (const c of part.children ?? []) walk(c, depth + 1);
    for (const h of held.get(id) ?? []) walk(h.id, depth + 1);
  };
  for (const n of Object.values(nodes)) if (n.parent == null) walk(n.id, 0);
  return out;
}

/** The click that names a part, for the panel: where in the code it is. */
export function sourceOfPart(page: string, part: PhonePart): Source {
  const file = part.file && part.file.startsWith("part:") ? `src/screens/${page}/${part.file.slice(5)}.tsx` : `src/screens/${page}.tsx`;
  return { file, line: part.line, component: part.type };
}
