import { useEffect, useState } from "react";
import { listPages, listSchemas, type SchemaListEntry } from "../../save/api";

/**
 * Legacy: list of slug paths (no extension), used to build the tree view
 * for `_layouts/` and as a fallback when `/schema-list` is unavailable.
 */
export function usePageList(apiBaseUrl: string): string[] {
  const [paths, setPaths] = useState<string[]>([]);
  useEffect(() => {
    listPages(apiBaseUrl)
      .then((r) => setPaths(r.paths))
      .catch(() => setPaths([]));
  }, [apiBaseUrl]);
  return paths;
}

/**
 * Flat schema listing with route + page_type metadata. Returns null while
 * loading or if the endpoint is unavailable (e.g. older backend) so callers
 * can decide whether to fall back to the tree view.
 */
export function useSchemaList(apiBaseUrl: string): SchemaListEntry[] | null {
  const [entries, setEntries] = useState<SchemaListEntry[] | null>(null);
  useEffect(() => {
    listSchemas(apiBaseUrl)
      .then((r) => setEntries(r))
      .catch(() => setEntries(null));
  }, [apiBaseUrl]);
  return entries;
}
