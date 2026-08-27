import { describe, it, expect } from "vitest";
import {
  hydrateFieldValue,
  hydrateFormValues,
  type HydrationFieldSpec,
} from "../src/util/formValueHydration";

/**
 * Regression coverage for B-021.6 — edit form not pre-filled. Every DB
 * value-shape the renderer might receive gets tested against the control
 * that would consume it.
 */

describe("hydrateFieldValue — date controls", () => {
  it("truncates ISO timestamps to YYYY-MM-DD for date input", () => {
    expect(hydrateFieldValue("2026-07-29T00:00:00.000Z", { kind: "date", name: "d" }))
      .toBe("2026-07-29");
  });
  it("passes through YYYY-MM-DD dates untouched", () => {
    expect(hydrateFieldValue("2026-07-29", { kind: "date", name: "d" }))
      .toBe("2026-07-29");
  });
  it("nulls/undefineds become empty string", () => {
    expect(hydrateFieldValue(null, { kind: "date", name: "d" })).toBe("");
    expect(hydrateFieldValue(undefined, { kind: "date", name: "d" })).toBe("");
  });

  it("datetime shapes ISO → YYYY-MM-DDTHH:MM", () => {
    expect(hydrateFieldValue("2026-07-29T14:30:00.000Z", { kind: "datetime", name: "d" }))
      .toBe("2026-07-29T14:30");
  });
});

describe("hydrateFieldValue — number", () => {
  it("coerces string number to number", () => {
    expect(hydrateFieldValue("42", { kind: "number", name: "n" })).toBe(42);
  });
  it("passes through actual numbers", () => {
    expect(hydrateFieldValue(3.14, { kind: "number", name: "n" })).toBe(3.14);
  });
  it("empty / null → empty string (uncontrolled placeholder)", () => {
    expect(hydrateFieldValue(null, { kind: "number", name: "n" })).toBe("");
    expect(hydrateFieldValue("", { kind: "number", name: "n" })).toBe("");
  });
  it("non-numeric strings → empty", () => {
    expect(hydrateFieldValue("nope", { kind: "number", name: "n" })).toBe("");
  });
});

describe("hydrateFieldValue — boolean controls (checkbox / switch)", () => {
  it("passes through real booleans", () => {
    expect(hydrateFieldValue(true, { kind: "checkbox", name: "b" })).toBe(true);
    expect(hydrateFieldValue(false, { kind: "checkbox", name: "b" })).toBe(false);
  });
  it("coerces postgres string booleans", () => {
    expect(hydrateFieldValue("true", { kind: "checkbox", name: "b" })).toBe(true);
    expect(hydrateFieldValue("false", { kind: "checkbox", name: "b" })).toBe(false);
  });
  it("coerces 't' / 'f' short forms", () => {
    expect(hydrateFieldValue("t", { kind: "checkbox", name: "b" })).toBe(true);
    expect(hydrateFieldValue("f", { kind: "checkbox", name: "b" })).toBe(false);
  });
  it("switch kind treated same as checkbox", () => {
    expect(hydrateFieldValue("1", { kind: "switch", name: "b" })).toBe(true);
    expect(hydrateFieldValue(0, { kind: "switch", name: "b" })).toBe(false);
  });
});

describe("hydrateFieldValue — select (FK)", () => {
  it("passes UUID FK strings through unchanged", () => {
    expect(hydrateFieldValue("abc-123-uuid", { kind: "select", name: "loc" }))
      .toBe("abc-123-uuid");
  });
  it("extracts .id from FK object shape", () => {
    expect(hydrateFieldValue({ id: "uuid-42", name: "Loc" }, { kind: "select", name: "loc" }))
      .toBe("uuid-42");
  });
  it("nulls → empty string (no pre-selection)", () => {
    expect(hydrateFieldValue(null, { kind: "select", name: "loc" })).toBe("");
  });
  it("radio kind treated same as select", () => {
    expect(hydrateFieldValue("option-a", { kind: "radio", name: "opt" })).toBe("option-a");
  });
});

describe("hydrateFieldValue — file upload", () => {
  it("stores string ref straight through", () => {
    expect(hydrateFieldValue("file-abc-123", { kind: "file", name: "cv" }))
      .toBe("file-abc-123");
  });
  it("extracts .id from file-ref object", () => {
    expect(hydrateFieldValue({ id: "f-1", url: "/api/files/f-1" }, { kind: "file", name: "cv" }))
      .toBe("f-1");
  });
  it("returns empty for null", () => {
    expect(hydrateFieldValue(null, { kind: "file", name: "cv" })).toBe("");
  });
});

describe("hydrateFieldValue — keyvalue (jsonb)", () => {
  it("converts jsonb object to array of key/value rows", () => {
    const out = hydrateFieldValue({ apiKey: "abc", timeout: 30 }, { kind: "keyvalue", name: "cfg" });
    expect(out).toEqual([
      { key: "apiKey", value: "abc" },
      { key: "timeout", value: 30 },
    ]);
  });
  it("passes through arrays untouched", () => {
    const rows = [{ key: "a", value: 1 }];
    expect(hydrateFieldValue(rows, { kind: "keyvalue", name: "cfg" })).toEqual(rows);
  });
  it("nulls → empty array (renders empty grid, not crash)", () => {
    expect(hydrateFieldValue(null, { kind: "keyvalue", name: "cfg" })).toEqual([]);
  });
  it("parses stringified JSON payload", () => {
    expect(hydrateFieldValue('{"a":1}', { kind: "keyvalue", name: "cfg" }))
      .toEqual([{ key: "a", value: 1 }]);
  });
});

describe("hydrateFieldValue — nested object", () => {
  it("recurses into sub-fields with their own hydrators", () => {
    const spec: HydrationFieldSpec = {
      kind: "object", name: "meta", fields: [
        { kind: "date", name: "publishedAt" },
        { kind: "checkbox", name: "featured" },
      ],
    };
    const out = hydrateFieldValue(
      { publishedAt: "2026-01-01T00:00:00Z", featured: "true" },
      spec,
    ) as Record<string, unknown>;
    expect(out.publishedAt).toBe("2026-01-01");
    expect(out.featured).toBe(true);
  });
});

describe("hydrateFieldValue — pass-through", () => {
  it("text kind passes strings unchanged", () => {
    expect(hydrateFieldValue("hello", { kind: "text", name: "t" })).toBe("hello");
  });
  it("null on text becomes empty string", () => {
    expect(hydrateFieldValue(null, { kind: "text", name: "t" })).toBe("");
  });
  it("unknown kind falls through without corruption", () => {
    expect(hydrateFieldValue("payload", { kind: "bespoke", name: "x" })).toBe("payload");
  });
});

describe("hydrateFormValues", () => {
  it("builds a full defaults dict from a record + field spec list", () => {
    const record = {
      name: "Bonsai",
      price: "48.00",
      inStock: "true",
      photoUrl: { id: "f-9" },
      plantedAt: "2026-03-14T10:00:00.000Z",
      nurseryLocationId: "uuid-nyc",
    };
    const fields: HydrationFieldSpec[] = [
      { kind: "text", name: "name" },
      { kind: "number", name: "price" },
      { kind: "checkbox", name: "inStock" },
      { kind: "file", name: "photoUrl" },
      { kind: "date", name: "plantedAt" },
      { kind: "select", name: "nurseryLocationId" },
    ];
    const out = hydrateFormValues(record, fields);
    expect(out.name).toBe("Bonsai");
    expect(out.price).toBe(48);
    expect(out.inStock).toBe(true);
    expect(out.photoUrl).toBe("f-9");
    expect(out.plantedAt).toBe("2026-03-14");
    expect(out.nurseryLocationId).toBe("uuid-nyc");
  });

  it("handles missing record keys — the field stays absent", () => {
    const out = hydrateFormValues(
      { name: "Bonsai" },
      [
        { kind: "text", name: "name" },
        { kind: "number", name: "price" },
      ],
    );
    expect(out.name).toBe("Bonsai");
    // price gets hydrated from undefined → empty string.
    expect(out.price).toBe("");
  });

  it("is idempotent — running twice matches once", () => {
    const record = {
      plantedAt: "2026-01-01T00:00:00Z",
      inStock: "true",
      cfg: { retries: 3 },
    };
    const fields: HydrationFieldSpec[] = [
      { kind: "date", name: "plantedAt" },
      { kind: "checkbox", name: "inStock" },
      { kind: "keyvalue", name: "cfg" },
    ];
    const once = hydrateFormValues(record, fields);
    const twice = hydrateFormValues(once, fields);
    expect(twice.plantedAt).toBe("2026-01-01");
    expect(twice.inStock).toBe(true);
    // keyvalue over an already-hydrated array stays an array (idempotent).
    expect(Array.isArray(twice.cfg)).toBe(true);
  });

  it("no fields → passes record through unchanged", () => {
    const record = { a: 1, b: "two" };
    expect(hydrateFormValues(record, undefined)).toEqual(record);
  });

  it("no record → empty object", () => {
    expect(hydrateFormValues(null, [{ kind: "text", name: "x" }])).toEqual({});
  });
});
