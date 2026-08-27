import { describe, it, expect } from "vitest";
import { applyCodeConnect } from "../src/code-connect";

describe("applyCodeConnect", () => {
  it("renames node.type per mappings", () => {
    const node: any = { id: "1", type: "PrimaryButton", props: { children: "Save" } };
    const mappings = {
      PrimaryButton: {
        libraryName: "Button",
        propsTransform: (p: any) => ({ label: p.children, variant: "primary" }),
      },
    };
    const out = applyCodeConnect(node, mappings);
    expect(out.type).toBe("Button");
    expect(out.props?.label).toBe("Save");
    expect(out.props?.variant).toBe("primary");
  });

  it("leaves unmapped nodes unchanged", () => {
    const node: any = { id: "2", type: "Box", props: { as: "div" }, children: [] };
    const mappings = {};
    const out = applyCodeConnect(node, mappings);
    expect(out.type).toBe("Box");
    expect(out.props?.as).toBe("div");
  });

  it("applies mappings recursively to children", () => {
    const node: any = {
      id: "1",
      type: "Card",
      children: [
        { id: "2", type: "PrimaryButton", props: { children: "OK" } },
        { id: "3", type: "Box", props: { as: "div" }, children: [] },
      ],
    };
    const mappings = {
      Card: { libraryName: "Card", propsTransform: (p: any) => p },
      PrimaryButton: {
        libraryName: "Button",
        propsTransform: (p: any) => ({ label: p.children }),
      },
    };
    const out = applyCodeConnect(node, mappings);
    expect(out.type).toBe("Card");
    expect(out.children?.[0].type).toBe("Button");
    expect(out.children?.[0].props?.label).toBe("OK");
    expect(out.children?.[1].type).toBe("Box");
  });

  it("handles node with no children", () => {
    const node: any = { id: "1", type: "IconButton", props: { icon: "star" } };
    const mappings = {
      IconButton: {
        libraryName: "Icon",
        propsTransform: (p: any) => ({ name: p.icon }),
      },
    };
    const out = applyCodeConnect(node, mappings);
    expect(out.type).toBe("Icon");
    expect(out.props?.name).toBe("star");
  });

  it("applies propsTransform result, not original props", () => {
    const node: any = { id: "1", type: "MyInput", props: { placeholder: "Enter text", disabled: true } };
    const mappings = {
      MyInput: {
        libraryName: "TextInput",
        propsTransform: (p: any) => ({ hint: p.placeholder }),
      },
    };
    const out = applyCodeConnect(node, mappings);
    expect(out.type).toBe("TextInput");
    expect(out.props?.hint).toBe("Enter text");
    // disabled is not in transform output
    expect(out.props?.disabled).toBeUndefined();
  });
});
