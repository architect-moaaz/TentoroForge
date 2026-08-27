export type SortDir = "asc" | "desc";
export interface SortState {
  sort: string | null;
  dir: SortDir;
}

/** Click cycle for a column header: new column -> asc -> desc -> cleared. */
export function nextSortState(current: SortState, column: string): SortState {
  if (current.sort !== column) return { sort: column, dir: "asc" };
  if (current.dir === "asc") return { sort: column, dir: "desc" };
  return { sort: null, dir: "asc" };
}

/** Build the data-viewer rows URL (page is 0-based). */
export function dbRowsUrl(
  projectId: string,
  table: string,
  page: number,
  pageSize: number,
  sort: string | null,
  dir: SortDir,
): string {
  const offset = page * pageSize;
  let url = `/api/projects/${projectId}/db/rows?table=${encodeURIComponent(table)}&limit=${pageSize}&offset=${offset}`;
  if (sort) url += `&sort=${encodeURIComponent(sort)}&dir=${dir}`;
  return url;
}
