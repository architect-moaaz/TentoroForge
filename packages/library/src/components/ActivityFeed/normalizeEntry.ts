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
  return {
    id: e.id ?? `entry-${i}`,
    actorName: String(via("actor") ?? actor.name ?? e.actorName ?? e.user ?? "Someone"),
    avatarUrl: actor.avatarUrl ?? e.avatarUrl,
    avatarInitials: actor.avatarInitials ?? e.avatarInitials,
    action: via("action") ?? e.action ?? e.verb ?? "",
    target: via("target") ?? e.target ?? e.subject ?? "",
    detail: via("detail") ?? e.detail ?? e.description,
    timestamp: via("timestamp") ?? e.timestamp ?? e.createdAt ?? "",
    category: e.category,
  };
}
