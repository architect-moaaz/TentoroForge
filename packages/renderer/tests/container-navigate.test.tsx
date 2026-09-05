/**
 * A Container carrying `navigate` is a drawn card the designer made
 * clickable. It keeps its children and its classes and gains only the
 * affordance; a Container without one is the plain box it always was.
 */
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Container } from "../src/nodes/layout/Container";

const render = (props: Record<string, unknown>) =>
  renderToString(
    <Container node={{ id: "c", props }}>{[<p key="a">After-Hours Protocol</p>, <p key="b">v2.1</p>]}</Container>,
  );

describe("Container navigate", () => {
  it("renders a link-role surface that keeps the drawn classes and children", () => {
    const html = render({ navigate: "/policies/[id]", className: "bg-white border rounded-[8px]" });
    expect(html).toContain('role="link"');
    expect(html).toContain('data-navigate="/policies/[id]"');
    expect(html).toContain("bg-white border rounded-[8px]");
    expect(html).toContain("After-Hours Protocol");
    expect(html).toContain("v2.1");
  });

  it("is a plain box without navigate", () => {
    const html = render({ className: "bg-white" });
    expect(html).not.toContain('role="link"');
    expect(html).not.toContain("cursor-pointer");
  });
});
