import { describe, expect, it } from "vitest";
import { ensureHumanLabel, humanizeLabel, looksLikeRawKey } from "../src/utils/humanizeLabel";

describe("humanizeLabel", () => {
  it("splits snake_case with digits (the document_5_tax case)", () => {
    expect(humanizeLabel("document_5_tax")).toBe("Document 5 Tax");
  });
  it("splits camelCase and uppercases acronyms", () => {
    expect(humanizeLabel("instructorId")).toBe("Instructor ID");
    expect(humanizeLabel("ocr_confidence")).toBe("OCR Confidence");
    expect(humanizeLabel("pdfUrl")).toBe("PDF URL");
  });
  it("splits kebab-case", () => {
    expect(humanizeLabel("start-time")).toBe("Start Time");
  });
  it("handles empty/nullish", () => {
    expect(humanizeLabel("")).toBe("");
    expect(humanizeLabel(null)).toBe("");
    expect(humanizeLabel(undefined)).toBe("");
  });
});

describe("looksLikeRawKey", () => {
  it("flags machine identifiers", () => {
    expect(looksLikeRawKey("hire_date")).toBe(true);
    expect(looksLikeRawKey("instructorId")).toBe(true);
    expect(looksLikeRawKey("start-time")).toBe(true);
  });
  it("passes deliberate copy through", () => {
    expect(looksLikeRawKey("Total Due")).toBe(false);
    expect(looksLikeRawKey("Status")).toBe(false);
    expect(looksLikeRawKey("status")).toBe(false);
  });
});

describe("ensureHumanLabel", () => {
  it("rewrites only raw keys", () => {
    expect(ensureHumanLabel("hire_date")).toBe("Hire Date");
    expect(ensureHumanLabel("Total Due")).toBe("Total Due");
  });
});
