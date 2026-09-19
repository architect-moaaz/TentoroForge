// The app SDK — stored files. Safe anywhere (a view, a load, a component).

const STORED = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Where the browser loads a file field's value from. An `image` field holds
 *  the stored file's id, which is not a URL; the app's preview route serves it.
 *  A value that is already a URL is returned as it is; an empty one as null. */
export function fileUrl(value: string | null | undefined): string | null {
  const s = String(value ?? "").trim();
  if (!s) return null;
  return STORED.test(s) ? `/api/files/preview?src=${encodeURIComponent(s)}` : s;
}
