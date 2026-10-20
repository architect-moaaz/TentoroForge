/** What is attached in the builder chat, waiting to go with the next message. */

/** A requirements document: read on upload, its text sent with the next message.
 *  A PDF may instead be a DESIGN (a Figma export, a designer's deck), whose
 *  pages go to the design agents and to Smith as pictures. */
export interface AttachedDocument {
  id: string;
  name: string;
  pages: number | null;
  truncated: boolean;
  /** A scan with no text layer, transcribed by Claude at upload. */
  transcribed?: boolean;
  /** Only a PDF can be either; a Word file is always requirements. */
  canBeDesign?: boolean;
  purpose?: "requirements" | "design";
  /** Its text could not be read (said in a toast); it can still be a design. */
  unreadable?: boolean;
}

/** A picture: a design to follow, or a screenshot of what the person means. */
export interface AttachedPicture {
  id: string;
  name: string;
  purpose: "design" | "problem";
}

/** What the chip says: the file, how much was read, and how. */
export function documentChipLabel(d: AttachedDocument): string {
  if (d.purpose === "design") return d.name;
  if (d.unreadable) return `${d.name} · not read`;
  const pages = d.pages ? ` · ${d.pages} page${d.pages === 1 ? "" : "s"}` : " · read";
  return `${d.name}${pages}${d.transcribed ? " · transcribed from scan" : ""}${d.truncated ? " (first part)" : ""}`;
}

/** The words on a chip's purpose toggle. */
export function purposeLabel(purpose: "requirements" | "design" | "problem"): string {
  return purpose === "design" ? "design to follow" : purpose === "problem" ? "shows a problem" : "requirements";
}

/** A picture's purpose when it arrives: before the app exists a picture is
 *  nearly always direction; once it is built, nearly always a report. The
 *  chip says which, and one click changes it. */
export function defaultPicturePurpose(appBuilt: boolean): AttachedPicture["purpose"] {
  return appBuilt ? "problem" : "design";
}

/** The project's design references after these attachments: those marked a
 *  design are added, every other one named here is taken out, and the rest
 *  stay as they were. */
export function nextDesignation(current: string[], changed: { id: string; purpose?: string }[]): string[] {
  const touched = new Set(changed.map((c) => c.id));
  const kept = current.filter((id) => !touched.has(id));
  return [...kept, ...changed.filter((c) => c.purpose === "design").map((c) => c.id)];
}

/** Files the server reads as text on upload — the ones worth a "Reading…" note. */
export function isDocumentFile(name: string): boolean {
  return /\.(pdf|docx|md|markdown|txt)$/i.test(name);
}
