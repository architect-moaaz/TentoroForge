/**
 * A list on the page — what is repeated, and how the server reads it: which
 * rows (where), in what order (sort), how many (limit). The read lives in
 * `load.ts` as `list("Entity", { … })`; the repeat lives in the view as
 * `source.map((row) => …)`.
 */
import type { EntityRef, LoadShape, PageDoc, ReadOptions } from "../types";
import { entityByName, pageSources, rowContext, type DataSource } from "./data";
import { humanise } from "./templates";

export interface ListRead {
  /** The load key the list comes from: `records` for `props.records`. */
  key: string;
  source: DataSource;
  entity: EntityRef | null;
  /** The read's options when they are plain values; null when code decides them. */
  options: ReadOptions | null;
  custom: boolean;
  /** Whether the read can be changed here: a `list`/`listPage` of an entity. */
  editable: boolean;
}

/** The list the node repeats over, or the list its row belongs to. */
export function listOf(doc: PageDoc, nodeId: string): ListRead | null {
  const model = doc.model;
  const node = model?.nodes[nodeId];
  if (!model || !node) return null;
  const sources = pageSources(doc);
  let source: DataSource | undefined;
  if (node.repeat) source = sources.find((s) => s.expr === node.repeat!.source);
  if (!source) {
    const row = rowContext(doc, nodeId);
    if (row?.listId) source = sources.find((s) => s.id === row.listId);
  }
  if (!source) return null;
  const shape = source.shape as LoadShape;
  const via = "via" in shape ? shape.via : undefined;
  const editable = !!via && via.how === "server" && (via.call === "list" || via.call === "listPage");
  return {
    key: source.id, source, entity: source.entity ?? entityByName(doc, "entity" in shape ? shape.entity : null),
    options: "options" in shape && shape.options ? shape.options : null,
    custom: !!("optionsCustom" in shape && shape.optionsCustom), editable,
  };
}

/** Sources a container can repeat over: lists the page loads. */
export function repeatableSources(doc: PageDoc): DataSource[] {
  return pageSources(doc).filter((s) => s.shape.kind === "rows" || s.shape.kind === "page" || s.shape.kind === "list" || s.shape.kind === "query");
}

/** The read's options in a sentence: "newest first, only where status is Open, 10 at most". */
export function optionsSummary(o: ReadOptions | null, entity: EntityRef | null): string {
  if (!o) return "every row, in the order they were added";
  const parts: string[] = [];
  const label = (f: string) => (entity?.fields.find((x) => x.name === f)?.label || humanise(f)).toLowerCase();
  if (o.sort) parts.push(`${o.order === "desc" ? "highest or newest" : "lowest or oldest"} ${label(o.sort)} first`);
  for (const [k, v] of Object.entries(o.where ?? {})) parts.push(`only where ${label(k)} is ${Array.isArray(v) ? v.join(" or ") : String(v)}`);
  if (o.search) parts.push(`matching “${o.search}”`);
  if (o.limit) parts.push(`${o.limit} at most`);
  return parts.length ? parts.join(", ") : "every row, in the order they were added";
}

/** A slug for a new list key: `records` for Record, `orderLines` for OrderLine. */
export function listKeyFor(entityName: string, taken: string[]): string {
  const base = entityName.replace(/^./, (c) => c.toLowerCase()).replace(/([^s])$/, "$1s");
  let key = base;
  for (let i = 2; taken.includes(key); i++) key = `${base}${i}`;
  return key;
}
