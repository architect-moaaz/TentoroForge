import { describe, expect, it } from "vitest";

import { colSpanFor, fieldIsFull, fieldOrder, fieldRemoval, reorderField, widthClassFor, withFieldSpan } from "../lib/fields";
import type { ObjectEntry, WorkflowInput } from "../types";

const str = (key: string, value: string): ObjectEntry => ({ key, kind: "string", value, code: JSON.stringify(value) });
const field = (name: string, ...inner: ObjectEntry[]): ObjectEntry => ({ key: name, kind: "object", code: "", entries: [str("label", name), ...inner] });
const fields = [field("fullName"), field("gender", str("kind", "select")), field("notes", str("kind", "textarea"))];
const input = (name: string, required: boolean): WorkflowInput => ({ name, kind: "string", type: "string", required, description: "", entity: null, options: [] });

describe("a form's fields as things a person moves", () => {
  it("moves a field before another, or to the end", () => {
    expect(fieldOrder(reorderField(fields, "notes", "fullName"))).toEqual(["notes", "fullName", "gender"]);
    expect(fieldOrder(reorderField(fields, "fullName", null))).toEqual(["gender", "notes", "fullName"]);
    expect(reorderField(fields, "gender", "gender")).toBe(fields);
    expect(fieldOrder(reorderField(fields, "missing", "gender"))).toEqual(["fullName", "gender", "notes"]);
  });

  it("widens a field to the whole row and back; a long text is always full", () => {
    expect(fieldIsFull(fields, "fullName")).toBe(false);
    expect(fieldIsFull(fields, "notes")).toBe(true);
    const wide = withFieldSpan(fields, "fullName", true);
    expect(fieldIsFull(wide, "fullName")).toBe(true);
    expect(wide[0].entries?.at(-1)).toEqual({ key: "span", kind: "string", value: "full", code: '"full"' });
    expect(fieldIsFull(withFieldSpan(wide, "fullName", false), "fullName")).toBe(false);
  });

  it("removes an optional field, and refuses a required one in plain words", () => {
    const gone = fieldRemoval(fields, "gender", input("gender", false));
    expect("entries" in gone && fieldOrder(gone.entries)).toEqual(["fullName", "notes"]);
    const kept = fieldRemoval(fields, "fullName", input("fullName", true));
    expect("refused" in kept && kept.refused).toMatch(/“fullName” is required by the workflow/);
    // a required field the page fills in is not shown, so it can go
    const fixed = [field("owner", { key: "value", kind: "expr", code: "props.me.id" })];
    expect("entries" in fieldRemoval(fixed, "owner", input("owner", true))).toBe(true);
  });
});

describe("the width a dragged edge means", () => {
  it("snaps to the nearest share of the parent", () => {
    expect(widthClassFor(0.52)).toBe("w-1/2");
    expect(widthClassFor(0.3)).toBe("w-1/3");
    expect(widthClassFor(0.97)).toBe("w-full");
    expect(widthClassFor(0.1)).toBe("w-1/4");
  });

  it("takes whole columns of a grid", () => {
    expect(colSpanFor(0.5, 4)).toBe(2);
    expect(colSpanFor(0.1, 3)).toBe(1);
    expect(colSpanFor(1, 3)).toBe(3);
  });
});
