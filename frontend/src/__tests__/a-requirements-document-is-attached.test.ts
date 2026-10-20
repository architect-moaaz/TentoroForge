/**
 * A BRD or PRD attached in the builder chat is shown as read, with its size,
 * and sent with the next message.
 */
import { describe, expect, it } from "vitest";
import { documentChipLabel, isDocumentFile } from "@/components/smith/attachedDocuments";

describe("an attached requirements document", () => {
  it("says the file and how much was read", () => {
    expect(documentChipLabel({ id: "a", name: "FitTrackr-BRD.docx", pages: 14, truncated: false })).toBe("FitTrackr-BRD.docx · 14 pages");
    expect(documentChipLabel({ id: "b", name: "notes.md", pages: null, truncated: false })).toBe("notes.md · read");
    expect(documentChipLabel({ id: "c", name: "Spec.pdf", pages: 1, truncated: true })).toBe("Spec.pdf · 1 page (first part)");
  });

  it("says when a scan was transcribed rather than read", () => {
    expect(documentChipLabel({ id: "d", name: "Signed-BRD.pdf", pages: 9, truncated: false, transcribed: true }))
      .toBe("Signed-BRD.pdf · 9 pages · transcribed from scan");
  });

  it("knows which files are read on upload", () => {
    expect(isDocumentFile("BRD.PDF")).toBe(true);
    expect(isDocumentFile("spec.docx")).toBe(true);
    expect(isDocumentFile("screen.png")).toBe(false);
  });
});
