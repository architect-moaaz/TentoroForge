/**
 * A DATA ROW IS NOT AN ITEM. List asks for `{title, subtitle}`, Timeline for
 * `{title, timestamp, actor, detail}`; a record page binds them to the rows
 * of a child collection — notes with `body` and `createdAt`, activity
 * entries with `summary` and `occurredAt` — and every row rendered blank.
 * The row's own columns say what its title and time are.
 */
const TITLE_KEYS = ["title", "name", "label", "subject", "summary", "body", "message", "description", "fileName", "filename", "caseNumber", "entryType"];
const TIME_KEYS = ["timestamp", "occurredAt", "createdAt", "uploadedAt", "decidedAt", "updatedAt"];
const ACTOR_KEYS = ["actor", "authorName", "userName", "decidedBy", "author", "uploadedBy"];

type Row = Record<string, unknown>;

const text = (v: unknown): string | undefined =>
  typeof v === "string" && v.trim() ? v : typeof v === "number" ? String(v) : undefined;

const humanise = (s: string): string =>
  s.replace(/[_-]+/g, " ").replace(/(?<=[a-z0-9])(?=[A-Z])/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function rowTime(row: Row): string | undefined {
  for (const k of TIME_KEYS) {
    const v = row[k];
    if (typeof v === "string" && v) return v;
    if (v instanceof Date) return v.toISOString();
  }
  return undefined;
}

export function rowTitle(row: Row): string {
  for (const k of TITLE_KEYS) {
    const v = text(row[k]);
    if (v) return k === "entryType" ? humanise(v) : v;
  }
  const first = Object.entries(row).find(([k, v]) => !/id$/i.test(k) && text(v) !== undefined);
  return first ? String(first[1]) : "";
}

export function rowSubtitle(row: Row): string | undefined {
  const t = rowTime(row);
  const when = t ? new Date(t) : undefined;
  const stamp = when && !isNaN(when.getTime()) ? when.toLocaleString() : undefined;
  const actor = ACTOR_KEYS.map((k) => text(row[k])).find(Boolean);
  return [stamp, actor].filter(Boolean).join(" · ") || undefined;
}

/** A List item from whatever the row is: an authored item stays as it is. */
export function asListItem(row: unknown): { title: string; subtitle?: string; icon?: string } {
  if (!row || typeof row !== "object") return { title: row == null ? "" : String(row) };
  const r = row as Row;
  if (text(r.title)) return r as { title: string; subtitle?: string; icon?: string };
  return { title: rowTitle(r), subtitle: text(r.subtitle) ?? rowSubtitle(r), icon: text(r.icon) };
}

/** A Timeline entry from whatever the row is. */
export function asTimelineEntry(row: unknown, i: number): Row {
  if (!row || typeof row !== "object") return { id: String(i), title: String(row ?? ""), timestamp: "" };
  const r = row as Row;
  if (text(r.title) && r.timestamp) return r;
  const detail = text(r.detail) ?? (r.fieldName ? `${humanise(String(r.fieldName))}: ${r.oldValue ?? "—"} → ${r.newValue ?? "—"}` : undefined);
  return { ...r, id: r.id ?? String(i), title: text(r.title) ?? rowTitle(r), timestamp: r.timestamp ?? rowTime(r) ?? "",
           actor: r.actor ?? ACTOR_KEYS.map((k) => text(r[k])).find(Boolean), detail };
}

const VALUE_KEYS = ["status", "state", "stage", "currentStage", "caseType", "type", "kind", "priority", "amountRequested", "amount", "value"];

/** A KeyValueList pair from whatever the row is: a case becomes
 *  "SC-STG-0001 · Open". An authored pair stays as it is. */
export function asKeyValue(row: unknown): { label: string; value: string; copyable?: boolean } {
  if (!row || typeof row !== "object") return { label: row == null ? "" : String(row), value: "" };
  const r = row as Row;
  if (text(r.label) !== undefined && "value" in r) return { label: String(r.label), value: r.value == null ? "" : String(r.value), copyable: r.copyable as boolean | undefined };
  const value = VALUE_KEYS.map((k) => text(r[k])).find(Boolean) ?? rowSubtitle(r) ?? "";
  return { label: rowTitle(r), value };
}
