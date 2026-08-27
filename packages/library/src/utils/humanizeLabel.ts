/**
 * humanizeLabel — renderer-level guarantee that raw data keys never
 * reach the user's eyes (G3).
 *
 * Upstream composers already humanize the labels they author, but any
 * label derived at RUNTIME from data itself — jsonb keys in
 * DescriptionList entries mode ("document_5_tax"), column keys used as
 * header fallbacks ("instructorId") — bypasses generation-time repair
 * entirely. This is the last line of defense, so it lives in the
 * renderer.
 *
 * "document_5_tax"  → "Document 5 Tax"
 * "instructorId"    → "Instructor ID"
 * "ocr_confidence"  → "OCR Confidence"
 */

/** Words that must render fully uppercase, not Title Case. */
const ACRONYMS = new Set([
  "id", "url", "uri", "ocr", "pdf", "api", "sku", "vat", "cv", "ssn",
  "ein", "qr", "ai", "fk", "gpa", "dob", "iban", "kyc",
]);

export function humanizeLabel(key: unknown): string {
  const s = String(key ?? "")
    .replace(/[_\-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Za-z])(\d)/g, "$1 $2")
    .replace(/(\d)([A-Za-z])/g, "$1 $2")
    .trim();
  if (!s) return "";
  return s
    .split(/\s+/)
    .map((w) => {
      const lower = w.toLowerCase();
      if (ACRONYMS.has(lower)) return lower.toUpperCase();
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(" ");
}

/**
 * True when a string reads as a machine identifier rather than
 * deliberate copy: no whitespace, and carrying snake/kebab separators
 * or a camelCase boundary. Deliberate labels ("Total Due", "Status")
 * pass through untouched — we only rewrite what a human plainly did
 * not write.
 */
export function looksLikeRawKey(s: unknown): boolean {
  const v = String(s ?? "");
  if (!v || /\s/.test(v)) return false;
  return /[_-]/.test(v) || /[a-z][A-Z]/.test(v);
}

/** Humanize only when the label looks machine-derived. */
export function ensureHumanLabel(s: unknown): string {
  const v = String(s ?? "");
  return looksLikeRawKey(v) ? humanizeLabel(v) : v;
}
