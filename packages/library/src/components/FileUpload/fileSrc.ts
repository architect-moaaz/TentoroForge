const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Where a browser can load a file value from. A stored file is kept as its id
 * (what FileUpload submits and an `image` column holds), which is not a URL;
 * the app's preview route serves it. A URL is already one.
 */
export function fileSrc(value: unknown): string {
  const s = String(value ?? "").trim();
  return UUID_RE.test(s) ? `/api/files/preview?src=${encodeURIComponent(s)}` : s;
}

export function isStoredFileId(value: unknown): boolean {
  return UUID_RE.test(String(value ?? "").trim());
}
