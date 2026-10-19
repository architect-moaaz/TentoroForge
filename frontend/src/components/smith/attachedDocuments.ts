/** A requirements document attached in the builder chat: read on upload,
 *  sent with the next message. */
export interface AttachedDocument {
  id: string;
  name: string;
  pages: number | null;
  truncated: boolean;
}

/** What the chip says: the file, how much was read, and when it was cut. */
export function documentChipLabel(d: AttachedDocument): string {
  const pages = d.pages ? ` · ${d.pages} page${d.pages === 1 ? "" : "s"}` : " · read";
  return `${d.name}${pages}${d.truncated ? " (first part)" : ""}`;
}
