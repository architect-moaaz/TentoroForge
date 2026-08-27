import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

describe("visibleIf", () => {
  it("hides node when expression is false", () => {
    const html = renderToString(
      renderNode(
        { id: "x", type: "Text", props: { content: "secret" }, visibleIf: "user.role == 'admin'" } as any,
        { data: {}, user: { role: "viewer" } } as any
      )
    );
    expect(html).not.toContain("secret");
  });

  it("treats expression error as false (no throw)", () => {
    const html = renderToString(
      renderNode(
        { id: "x", type: "Text", props: { content: "x" }, visibleIf: "??bad??" } as any,
        { data: {} } as any
      )
    );
    expect(html).toBe("");
  });
});
