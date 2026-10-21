/**
 * A BRD or PRD attached in the builder chat is shown as read, with its size,
 * and sent with the next message.
 */
import { describe, expect, it } from "vitest";
import {
  defaultPicturePurpose,
  documentChipLabel,
  isDocumentFile,
  nextDesignation,
  purposeLabel,
} from "@/components/smith/attachedDocuments";

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

describe("what an attachment is for", () => {
  it("defaults a picture to a design before the app exists and to a problem after", () => {
    expect(defaultPicturePurpose(false)).toBe("design");
    expect(defaultPicturePurpose(true)).toBe("problem");
  });

  it("keeps the project's earlier references and follows each chip's purpose", () => {
    const now = ["old-ref", "mock", "bug"];
    expect(nextDesignation(now, [{ id: "mock", purpose: "design" }, { id: "bug", purpose: "problem" },
                                 { id: "new-pdf", purpose: "design" }, { id: "brd", purpose: "requirements" }]))
      .toEqual(["old-ref", "mock", "new-pdf"]);
    // A removed chip (no purpose) is no longer a reference.
    expect(nextDesignation(["a", "b"], [{ id: "a" }])).toEqual(["b"]);
  });

  it("says a design PDF is a design, not pages read", () => {
    expect(documentChipLabel({ id: "e", name: "Mockups.pdf", pages: 12, truncated: false, purpose: "design" })).toBe("Mockups.pdf");
    expect(purposeLabel("design")).toBe("design to follow");
    expect(purposeLabel("problem")).toBe("shows a problem");
  });
});
