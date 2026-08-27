import { describe, it, expect } from "vitest";
import { InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode }
  from "../../src/nodes/inputs";

// === Spec happy-path tests ===

describe("InputNode", () => {
  it("name + label + type required", () => {
    const r = InputNode.parse({
      id: "i", type: "Input",
      props: { name: "email", label: "Email", type: "email",
               validators: { required: true } },
    });
    expect(r.props.type).toBe("email");
    expect(r.props.validators?.required).toBe(true);
  });
});

describe("SelectNode", () => {
  it("options non-empty", () => {
    expect(() => SelectNode.parse({ id: "s", type: "Select",
      props: { name: "x", label: "X", options: [] } })).toThrow();
    const r = SelectNode.parse({
      id: "s", type: "Select",
      props: { name: "role", label: "Role",
               options: [{ value: "a", label: "A" }] },
    });
    expect(r.props.options.length).toBe(1);
  });
});

describe("TextareaNode", () => {
  it("rows positive int", () => {
    expect(TextareaNode.parse({ id: "t", type: "Textarea",
      props: { name: "n", label: "N", rows: 4 } }).props.rows).toBe(4);
  });
});

describe("CheckboxNode", () => {
  it("name + label", () => {
    expect(CheckboxNode.parse({ id: "c", type: "Checkbox",
      props: { name: "agree", label: "Agree" } }).props.name).toBe("agree");
  });
});

describe("DatePickerNode", () => {
  it("optional min/max", () => {
    expect(DatePickerNode.parse({ id: "d", type: "DatePicker",
      props: { name: "dob", label: "DOB", min: "1900-01-01" } })
      .props.min).toBe("1900-01-01");
  });
});

// === v2 strict-mode + edge-case tests (per locked-in conventions) ===

describe("inputs strict mode", () => {
  it("InputNode rejects unknown props", () => {
    expect(() => InputNode.parse({
      id: "i", type: "Input",
      props: { name: "e", label: "E", type: "email", whoops: 1 },
    })).toThrow();
  });

  it("InputNode rejects empty name or label", () => {
    expect(() => InputNode.parse({
      id: "i", type: "Input",
      props: { name: "", label: "E", type: "email" },
    })).toThrow();
    expect(() => InputNode.parse({
      id: "i", type: "Input",
      props: { name: "e", label: "", type: "email" },
    })).toThrow();
  });

  it("InputNode rejects invalid type enum", () => {
    expect(() => InputNode.parse({
      id: "i", type: "Input",
      props: { name: "e", label: "E", type: "color" },
    })).toThrow();
  });

  it("InputNode validators rejects unknown keys", () => {
    expect(() => InputNode.parse({
      id: "i", type: "Input",
      props: { name: "e", label: "E", type: "email",
               validators: { required: true, whoops: 1 } },
    })).toThrow();
  });

  it("SelectNode requires non-empty option labels and values", () => {
    expect(() => SelectNode.parse({
      id: "s", type: "Select",
      props: { name: "x", label: "X",
               options: [{ value: "", label: "Empty" }] },
    })).toThrow();
    expect(() => SelectNode.parse({
      id: "s", type: "Select",
      props: { name: "x", label: "X",
               options: [{ value: "a", label: "" }] },
    })).toThrow();
  });

  it("TextareaNode rejects 0 or negative rows", () => {
    expect(() => TextareaNode.parse({
      id: "t", type: "Textarea",
      props: { name: "n", label: "N", rows: 0 },
    })).toThrow();
    expect(() => TextareaNode.parse({
      id: "t", type: "Textarea",
      props: { name: "n", label: "N", rows: -1 },
    })).toThrow();
  });

  it("TextareaNode defaults rows to 4 when omitted", () => {
    const r = TextareaNode.parse({
      id: "t", type: "Textarea",
      props: { name: "n", label: "N" },
    });
    expect(r.props.rows).toBe(4);
  });

  it("CheckboxNode rejects empty id, name, or label", () => {
    expect(() => CheckboxNode.parse({
      id: "", type: "Checkbox",
      props: { name: "a", label: "A" },
    })).toThrow();
    expect(() => CheckboxNode.parse({
      id: "c", type: "Checkbox",
      props: { name: "", label: "A" },
    })).toThrow();
    expect(() => CheckboxNode.parse({
      id: "c", type: "Checkbox",
      props: { name: "a", label: "" },
    })).toThrow();
  });

  it("DatePickerNode accepts both min and max", () => {
    const r = DatePickerNode.parse({
      id: "d", type: "DatePicker",
      props: { name: "dob", label: "DOB",
               min: "1900-01-01", max: "2099-12-31" },
    });
    expect(r.props.min).toBe("1900-01-01");
    expect(r.props.max).toBe("2099-12-31");
  });
});
