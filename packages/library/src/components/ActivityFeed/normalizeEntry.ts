/**
 * One raw row -> the shape the feed row renderer expects.
 *
 * `fields` is a map the dashboard composer derives from the bound entity's
 * REAL columns (see services/widget_data_contract.py). ActivityFeed's contract
 * is {actor:{name}, action, target, timestamp}; an entity like Notification has
 * {recipientName, type, message, createdAt} and matches none of them, so every
 * row used to render the "Someone" placeholder. The map is how the two halves
 * of that contract are introduced.
 *
 * A native-shaped entry still works with no map, and a map naming a column the
 * row does not have falls through to the same defaults rather than blanking —
 * a wrong map should degrade to today's behaviour, not to an empty feed.
 */
export type FeedFieldMap = Partial<
  Record<"actor" | "action" | "target" | "timestamp" | "detail", string>
>;

export function normalizeEntry(raw: unknown, i: number, fields?: FeedFieldMap) {
  const e = (raw && typeof raw === "object" ? raw : {}) as Record<string, any>;
  const actor = (e.actor && typeof e.actor === "object" ? e.actor : {}) as Record<string, any>;
  const via = (key: keyof FeedFieldMap) => {
    const col = fields?.[key];
    return col ? e[col] : undefined;
  };
  // A DATA ROW SAYS WHAT HAPPENED. An activity log entry carries `summary`
  // and `occurredAt`, a note `body` and `createdAt`; with no field map the
  // feed showed "Someone" doing nothing at no time. The row's own columns
  // fill each slot, and an actor the row does not name is left unnamed
  // rather than invented.
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : undefined);
  const actorName = via("actor") ?? actor.name ?? e.actorName ?? e.user
    ?? str(e.authorName) ?? str(e.userName) ?? str(e.decidedBy) ?? (typeof e.actor === "string" ? e.actor : undefined);
  const category = e.category ?? categoryOf(str(e.entryType) ?? str(e.kind) ?? str(e.type));
  return {
    id: e.id ?? `entry-${i}`,
    actorName: actorName === undefined ? "" : String(actorName),
    avatarUrl: actor.avatarUrl ?? e.avatarUrl,
    avatarInitials: actor.avatarInitials ?? e.avatarInitials,
    action: via("action") ?? e.action ?? e.verb ?? str(e.summary) ?? str(e.message) ?? str(e.title) ?? str(e.body) ?? humanise(str(e.entryType)) ?? "",
    target: via("target") ?? e.target ?? e.subject ?? "",
    detail: via("detail") ?? e.detail ?? e.description,
    timestamp: via("timestamp") ?? e.timestamp ?? e.occurredAt ?? e.createdAt ?? e.decidedAt ?? e.updatedAt ?? "",
    category,
  };
}

function humanise(v: string | undefined): string | undefined {
  return v ? v.replace(/[_-]+/g, " ").replace(/(?<=[a-z0-9])(?=[A-Z])/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : undefined;
}

/** The feed's category, read off a log entry's own type where it says one. */
function categoryOf(kind: string | undefined): "create" | "update" | "approve" | "reject" | "comment" | "system" | undefined {
  if (!kind) return undefined;
  const k = kind.toLowerCase();
  if (/creat|raised|submitted|new/.test(k)) return "create";
  if (/approv|decision/.test(k)) return "approve";
  if (/den|reject|withdraw/.test(k)) return "reject";
  if (/note|comment|information/.test(k)) return "comment";
  if (/status|stage|update|post|override|change/.test(k)) return "update";
  return undefined;
}
