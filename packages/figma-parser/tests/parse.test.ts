import { describe, it, expect } from "vitest";
import { parseJsxToSchema } from "../src/parse";

describe("parseJsxToSchema", () => {
  it("returns empty schema for empty input", () => {
    const result = parseJsxToSchema("");
    expect(result.schema).toEqual({
      root: { id: expect.any(String), type: "Box", children: [] },
    });
    expect(result.unmappedNodes).toEqual([]);
  });

  it("parses a simple <div> as Box primitive", () => {
    const result = parseJsxToSchema(`<div>hello</div>`);
    expect(result.schema.root.type).toBe("Box");
    expect(result.schema.root.children?.length).toBe(1);
    expect(result.schema.root.children?.[0].type).toBe("Text");
    expect(result.schema.root.children?.[0].props?.content).toBe("hello");
  });

  it("parses <button> as Button with label from text content", () => {
    const result = parseJsxToSchema(`<button>Submit</button>`);
    expect(result.schema.root.type).toBe("Button");
    expect(result.schema.root.props?.label).toBe("Submit");
  });

  it("parses <img> as Image with src and alt", () => {
    const result = parseJsxToSchema(`<img src="/logo.png" alt="Logo" />`);
    expect(result.schema.root.type).toBe("Image");
    expect(result.schema.root.props?.src).toBe("/logo.png");
    expect(result.schema.root.props?.alt).toBe("Logo");
  });

  it("parses nested div with text", () => {
    const result = parseJsxToSchema(`<section><div>Title</div></section>`);
    expect(result.schema.root.type).toBe("Box");
    expect(result.schema.root.props?.as).toBe("section");
    expect(result.schema.root.children?.length).toBe(1);
    expect(result.schema.root.children?.[0].type).toBe("Box");
    expect(result.schema.root.children?.[0].children?.[0].type).toBe("Text");
    expect(result.schema.root.children?.[0].children?.[0].props?.content).toBe("Title");
  });

  it("maps semantic block tags to Box with as prop", () => {
    const tags = ["div", "section", "header", "footer", "main", "article", "aside", "nav"];
    for (const tag of tags) {
      const result = parseJsxToSchema(`<${tag}></${tag}>`);
      expect(result.schema.root.type).toBe("Box");
      expect(result.schema.root.props?.as).toBe(tag);
    }
  });

  it("maps unknown element as Box fallback", () => {
    const result = parseJsxToSchema(`<span>text</span>`);
    expect(result.schema.root.type).toBe("Box");
  });
});
