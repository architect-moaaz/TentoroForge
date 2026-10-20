/** A requirements document attached in the builder chat: read on upload,
 *  sent with the next message. */
export interface AttachedDocument {
  id: string;
  name: string;
  pages: number | null;
  truncated: boolean;
  /** A scan with no text layer, transcribed by Claude at upload. */
  transcribed?: boolean;
}

/** What the chip says: the file, how much was read, and how. */
export function documentChipLabel(d: AttachedDocument): string {
  const pages = d.pages ? ` · ${d.pages} page${d.pages === 1 ? "" : "s"}` : " · read";
  return `${d.name}${pages}${d.transcribed ? " · transcribed from scan" : ""}${d.truncated ? " (first part)" : ""}`;
}

/** Files the server reads as text on upload — the ones worth a "Reading…" note. */
export function isDocumentFile(name: string): boolean {
  return /\.(pdf|docx|md|markdown|txt)$/i.test(name);
}
