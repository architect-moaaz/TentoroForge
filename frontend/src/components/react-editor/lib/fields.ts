/**
 * A form's fields as things a person moves, widens and removes — over the
 * `fields={{ … }}` object a WorkflowForm draws in source order — and the
 * width a dragged edge means for an element.
 */
import type { ObjectEntry, WorkflowInput } from "../types";
import { entry, entryString } from "./data";
import { humanise } from "./templates";

/** The fields the form shows, in the order it draws them. */
export function fieldOrder(entries: ObjectEntry[]): string[] {
  return entries.map((e) => e.key);
}

/** The label a field wears, for messages. */
export function fieldLabel(entries: ObjectEntry[], name: string): string {
  const e = entry(entries, name);
  return (e && e.kind === "object" && entryString(e.entries, "label")) || humanise(name);
}

/** `name` moved to sit before `beforeName`, or last when that is null. */
export function reorderField(entries: ObjectEntry[], name: string, beforeName: string | null): ObjectEntry[] {
  const moving = entry(entries, name);
  if (!moving || name === beforeName) return entries;
  const rest = entries.filter((e) => e.key !== name);
  const at = beforeName ? rest.findIndex((e) => e.key === beforeName) : -1;
  if (at < 0) return [...rest, moving];
  return [...rest.slice(0, at), moving, ...rest.slice(at)];
}

/** Whether a field takes the whole row of a two-column form. */
export function fieldIsFull(entries: ObjectEntry[], name: string): boolean {
  const e = entry(entries, name);
  if (!e || e.kind !== "object") return false;
  return entryString(e.entries, "span") === "full" || entryString(e.entries, "kind") === "textarea";
}

/** The field made full-width, or back to half. */
export function withFieldSpan(entries: ObjectEntry[], name: string, full: boolean): ObjectEntry[] {
  return entries.map((e) => {
    if (e.key !== name || e.kind !== "object") return e;
    const inner = (e.entries ?? []).filter((x) => x.key !== "span");
    return { ...e, entries: full ? [...inner, { key: "span", kind: "string", value: "full", code: '"full"' }] : inner };
  });
}

/**
 * The form without `name` — or why it has to stay: the workflow requires it,
 * so leaving it out would make every submission fail.
 */
export function fieldRemoval(entries: ObjectEntry[], name: string, input: WorkflowInput | null | undefined): { entries: ObjectEntry[] } | { refused: string } {
  const e = entry(entries, name);
  if (!e) return { entries };
  const fixed = e.kind === "object" && !!entry(e.entries, "value");
  if (input?.required && !fixed) {
    return { refused: `“${fieldLabel(entries, name)}” is required by the workflow — the form cannot leave it out. In Settings, have the page fill it in instead, or ask Smith to make it optional.` };
  }
  return { entries: entries.filter((x) => x.key !== name) };
}

/** The width classes an edge can be dragged to, as shares of the parent. */
export const WIDTH_STOPS: { cls: string; share: number }[] = [
  { cls: "w-1/4", share: 0.25 }, { cls: "w-1/3", share: 1 / 3 }, { cls: "w-1/2", share: 0.5 },
  { cls: "w-2/3", share: 2 / 3 }, { cls: "w-3/4", share: 0.75 }, { cls: "w-full", share: 1 },
];

/** The nearest width stop to a share of the parent's width. */
export function widthClassFor(share: number): string {
  let best = WIDTH_STOPS[0];
  for (const s of WIDTH_STOPS) if (Math.abs(s.share - share) < Math.abs(best.share - share)) best = s;
  return best.cls;
}

/** In a grid of `cols` columns, how many a share of the width takes. */
export function colSpanFor(share: number, cols: number): number {
  return Math.min(cols, Math.max(1, Math.round(share * cols)));
}
