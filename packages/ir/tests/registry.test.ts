import { describe, it, expect } from "vitest";
import {
  getNodeSpec,
  getAllNodeTypes,
  getNodeTypesByCategory,
  isValidNodeType,
  isValidProp,
  getRequiredProps,
} from "../src/registry.js";

describe("Node Registry", () => {
  it("should have all 36 node types registered", () => {
    const types = getAllNodeTypes();
    expect(types.length).toBe(38);
  });

  it("should return spec for known types", () => {
    const stack = getNodeSpec("Stack");
    expect(stack).toBeDefined();
    expect(stack!.category).toBe("layout");
    expect(stack!.hasChildren).toBe(true);

    const text = getNodeSpec("Text");
    expect(text).toBeDefined();
    expect(text!.category).toBe("content");
    expect(text!.hasChildren).toBe(false);
  });

  it("should return undefined for unknown types", () => {
    expect(getNodeSpec("Nonexistent")).toBeUndefined();
  });

  it("should validate node type existence", () => {
    expect(isValidNodeType("Stack")).toBe(true);
    expect(isValidNodeType("Row")).toBe(true);
    expect(isValidNodeType("TextInput")).toBe(true);
    expect(isValidNodeType("DataTable")).toBe(true);
    expect(isValidNodeType("FakeWidget")).toBe(false);
  });

  it("should validate props", () => {
    expect(isValidProp("Stack", "gap")).toBe(true);
    expect(isValidProp("Stack", "padding")).toBe(true);
    expect(isValidProp("Stack", "nonexistent")).toBe(false);
    expect(isValidProp("Text", "content")).toBe(true);
    expect(isValidProp("Text", "typography")).toBe(true);
    expect(isValidProp("FakeWidget", "anything")).toBe(false);
  });

  it("should return required props", () => {
    const textRequired = getRequiredProps("Text");
    expect(textRequired.some((p) => p.name === "content")).toBe(true);

    const inputRequired = getRequiredProps("TextInput");
    expect(inputRequired.some((p) => p.name === "bind")).toBe(true);

    const tableRequired = getRequiredProps("DataTable");
    expect(tableRequired.some((p) => p.name === "data")).toBe(true);
    expect(tableRequired.some((p) => p.name === "columns")).toBe(true);
  });

  it("should categorize nodes correctly", () => {
    const layouts = getNodeTypesByCategory("layout");
    expect(layouts.map((s) => s.type)).toContain("Stack");
    expect(layouts.map((s) => s.type)).toContain("Row");
    expect(layouts.map((s) => s.type)).toContain("Grid");

    const inputs = getNodeTypesByCategory("input");
    expect(inputs.map((s) => s.type)).toContain("TextInput");
    expect(inputs.map((s) => s.type)).toContain("Select");
    expect(inputs.map((s) => s.type)).toContain("DatePicker");

    const composites = getNodeTypesByCategory("composite");
    expect(composites.map((s) => s.type)).toContain("DataTable");
    expect(composites.map((s) => s.type)).toContain("Form");
    expect(composites.map((s) => s.type)).toContain("Chart");
  });

  it("should have layout nodes that accept children", () => {
    const layouts = getNodeTypesByCategory("layout");
    const containerLayouts = layouts.filter((s) => s.type !== "Spacer" && s.type !== "Divider");
    for (const spec of containerLayouts) {
      expect(spec.hasChildren).toBe(true);
    }
  });

  it("should have input nodes that require bind prop", () => {
    const inputs = getNodeTypesByCategory("input");
    for (const spec of inputs) {
      const bindProp = spec.props.find((p) => p.name === "bind");
      expect(bindProp).toBeDefined();
      expect(bindProp!.required).toBe(true);
    }
  });
});
