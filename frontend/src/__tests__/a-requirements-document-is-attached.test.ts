/**
 * A BRD or PRD attached in the builder chat is shown as read, with its size,
 * and sent with the next message.
 */
import { describe, expect, it } from "vitest";
import { documentChipLabel } from "@/components/smith/attachedDocuments";

describe("an attached requirements document", () => {
  it("says the file and how much was read", () => {
    expect(documentChipLabel({ id: "a", name: "FitTrackr-BRD.docx", pages: 14, truncated: false })).toBe("FitTrackr-BRD.docx · 14 pages");
    expect(documentChipLabel({ id: "b", name: "notes.md", pages: null, truncated: false })).toBe("notes.md · read");
    expect(documentChipLabel({ id: "c", name: "Spec.pdf", pages: 1, truncated: true })).toBe("Spec.pdf · 1 page (first part)");
  });
});
