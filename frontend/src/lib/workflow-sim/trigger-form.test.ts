import { describe, it, expect } from "vitest";
import { extractTriggerFields, coerceTriggerValues } from "./trigger-form";

const def = {
  id: "w", name: "W",
  processVariables: [
    { name: "days", type: "number", required: true },
    { name: "reason", type: "string", defaultValue: "PTO" },
    { name: "urgent", type: "boolean" },
  ],
  definition: { trigger: {}, nodes: [], edges: [] },
} as any;

describe("extractTriggerFields", () => {
  it("maps processVariables to field specs with defaults", () => {
    const fields = extractTriggerFields(def);
    expect(fields).toEqual([
      { name: "days", type: "number", required: true, defaultValue: undefined, description: undefined },
      { name: "reason", type: "string", required: false, defaultValue: "PTO", description: undefined },
      { name: "urgent", type: "boolean", required: false, defaultValue: undefined, description: undefined },
    ]);
  });

  it("returns [] when there are no processVariables", () => {
    expect(extractTriggerFields({ ...def, processVariables: undefined })).toEqual([]);
  });
});

describe("coerceTriggerValues", () => {
  it("coerces raw string inputs by declared type", () => {
    const fields = extractTriggerFields(def);
    const out = coerceTriggerValues(fields, { days: "3", reason: "Trip", urgent: "true" });
    expect(out).toEqual({ days: 3, reason: "Trip", urgent: true });
  });

  it("omits empty optional fields and applies defaults", () => {
    const fields = extractTriggerFields(def);
    const out = coerceTriggerValues(fields, { days: "1", reason: "", urgent: "" });
    expect(out).toEqual({ days: 1, reason: "PTO" });
  });

  it("keeps a non-numeric string as-is instead of emitting NaN", () => {
    const fields = extractTriggerFields(def);
    const out = coerceTriggerValues(fields, { days: "abc" });
    expect(out.days).toBe("abc");
  });

  it("falls back to the raw string when object/array JSON is malformed", () => {
    const fields = extractTriggerFields({ ...def, processVariables: [{ name: "meta", type: "object" }] } as any);
    const out = coerceTriggerValues(fields, { meta: "{bad json" });
    expect(out.meta).toBe("{bad json");
  });
});
