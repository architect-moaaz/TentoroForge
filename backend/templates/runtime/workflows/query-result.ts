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
 * So the single row's fields ride alongside `rows` and `count`, which keep
 * their own names if a column shares one.
 */
export function queryResult(rows: unknown): Record<string, unknown> {
  const list = Array.isArray(rows) ? rows : [];
  const first = (list.length === 1 ? list[0] : null) as Record<string, unknown> | null;
  return { ...(first ?? {}), rows: list, count: list.length };
}
