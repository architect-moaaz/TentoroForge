/**
 * What a lookup step publishes.
 *
 * `db_query` answers `{rows, count}`. A step written to fetch ONE record is
 * read as that record by whoever comes after it — `check_member_verified.
 * kycStatus`, `fetch_tool_owner.ownerId`. Templates had a fallback for that
 * (`_firstRowFallback`); a CONDITION had none, so "List a Tool" asked whether
 * the member was verified, read `undefined`, and told every member — verified
 * or not — to "complete identity verification first" (0l133sp2).
 *
 * So the first row's fields ride alongside `rows` and `count`, which keep
 * their own names if a column shares one. FIRST ROW WHENEVER THERE IS ONE,
 * not only when there is exactly one: AquaTrack's "Set Daily Goal" looked up
 * the person's active goal, found three, read `find_active_goal.id` as null,
 * and never superseded any of them (m1dck85j, 2026-10-12) — while a template
 * over the same step (`_firstRowFallback`) read the first row's id. A step
 * and a condition now read the same record.
 */
export function queryResult(rows: unknown): Record<string, unknown> {
  const list = Array.isArray(rows) ? rows : [];
  const first = (list.length > 0 ? list[0] : null) as Record<string, unknown> | null;
  // …AND `output`, the name every other step answers to. F&B's "already
  // exists" check counted `check_existing.output`, which was not there, and
  // every new category was refused (2026-10-01).
  return { ...(first ?? {}), rows: list, count: list.length, output: list };
}
