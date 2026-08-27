import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

// greeting.text path: DataBinding requires path: z.string().min(1), so we
// use a nested path rather than an empty path to the top-level string.
const ctx = { data: { greeting: { text: "hello" } } } as any;

describe("Text renderer", () => {
  it("renders props.content", () => {
    const html = renderToString(
      renderNode({ id: "t", type: "Text", props: { content: "hi", as: "p" } } as any, ctx)
    );
    expect(html).toContain("<p");
    expect(html).toContain("hi");
  });

  it("renders bound content via resolveBinding", () => {
    const html = renderToString(
      renderNode(
        { id: "t2", type: "Text", bind: { source: "greeting", path: "text" } } as any,
        ctx
      )
    );
    expect(html).toContain("hello");
  });
});

describe("Box renderer", () => {
  it("renders with data-node-id and children", () => {
    const html = renderToString(
      renderNode(
        {
          id: "b1",
          type: "Box",
          style: { padding: "spacing.4" },
          children: [{ id: "t", type: "Text", props: { content: "inside" } }],
        } as any,
        ctx
      )
    );
    expect(html).toContain('data-node-id="b1"');
    expect(html).toContain("var(--token-spacing-4)");
    expect(html).toContain("inside");
  });
});

describe("Image renderer", () => {
  it("renders alt and src", () => {
    const html = renderToString(
      renderNode({ id: "i", type: "Image", props: { src: "/x.png", alt: "x" } } as any, ctx)
    );
    expect(html).toContain('src="/x.png"');
    expect(html).toContain('alt="x"');
  });
});
