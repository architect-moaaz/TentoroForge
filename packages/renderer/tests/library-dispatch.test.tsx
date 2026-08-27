// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { z } from "zod";
import { renderNode } from "../src/runtime/dispatch";

// Construct a minimal inline registry shape — avoids cross-package dep on @tentoroforge/library
// while still exercising the full dispatch path.
const Tag = ({ label }: { label: string }) => <span data-testid="tag">{label}</span>;

const inlineRegistry = {
  has: (name: string) => name === "Tag",
  get: (name: string) =>
    name === "Tag"
      ? {
          name: "Tag",
          component: Tag,
          propsSchema: z.object({ label: z.string() }).strict(),
          category: "static" as const,
          acceptsChildren: false,
        }
      : undefined,
  validateProps: (name: string, props: unknown) => {
    if (name !== "Tag") throw new Error(`'${name}' not registered`);
    return z.object({ label: z.string() }).strict().parse(props);
  },
  register: () => { throw new Error("read-only stub"); },
  list: () => [],
};

describe("Library node dispatch", () => {
  it("dispatches a registered library node type and renders its component", () => {
    const node = {
      id: "tag1",
      type: "Tag",
      props: { label: "hello" },
    };
    const el = renderNode(node as any, { data: {}, registry: inlineRegistry });
    const html = renderToString(el as any);
    expect(html).toContain("hello");
  });

  it("validates props against the registered propsSchema", () => {
    const badNode = {
      id: "tag2",
      type: "Tag",
      props: { label: 123 }, // wrong type
    };
    expect(() =>
      renderNode(badNode as any, { data: {}, registry: inlineRegistry })
    ).toThrow();
  });

  it("throws clearly when node type is unknown and not in registry", () => {
    const unknownNode = {
      id: "x1",
      type: "UnknownWidget",
      props: {},
    };
    expect(() =>
      renderNode(unknownNode as any, { data: {}, registry: inlineRegistry })
    ).toThrow(/unsupported type|not found|UnknownWidget/i);
  });

  it("falls through to library dispatch when no registry is provided and type is unknown", () => {
    const unknownNode = {
      id: "x2",
      type: "SomeCustomThing",
      props: {},
    };
    // Without registry, should throw standard unsupported-type error
    expect(() =>
      renderNode(unknownNode as any, { data: {} })
    ).toThrow(/unsupported type|SomeCustomThing/i);
  });

  it("passes children through to library component", () => {
    const nodeWithChildren = {
      id: "tag3",
      type: "Tag",
      props: { label: "parent" },
      children: [],
    };
    const el = renderNode(nodeWithChildren as any, { data: {}, registry: inlineRegistry });
    const html = renderToString(el as any);
    expect(html).toContain("parent");
  });
});
