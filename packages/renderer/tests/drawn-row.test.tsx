/**
 * A class that declares `flex` is a drawn row: its gap and its wrap are its
 * own. Row's default `flex-wrap` put an icon under the title it was drawn
 * beside; Stack's default gap spaced a KPI's label from its number by 16px
 * the design never had. Authored layouts that state nothing keep the defaults.
 */
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Row } from "../src/nodes/layout/Row";
import { Stack } from "../src/nodes/layout/Stack";

const cls = (html: string) => (/class="([^"]*)"/.exec(html)?.[1] ?? "").split(" ");
const row = (props: Record<string, unknown>) =>
  cls(renderToString(<Row node={{ id: "r", props }}>{[<p key="a">a</p>, <p key="b">b</p>]}</Row>));
const stack = (props: Record<string, unknown>) =>
  cls(renderToString(<Stack node={{ id: "s", props }}>{[<p key="a">a</p>]}</Stack>));

describe("a drawn row keeps its own layout", () => {
  it("does not wrap a drawn row unless the drawing said so", () => {
    expect(row({ className: "flex items-start justify-between w-full" })).not.toContain("flex-wrap");
    expect(row({ className: "flex flex-wrap gap-[16px]" })).toContain("flex-wrap");
  });
  it("adds no gap to a drawn row or stack", () => {
    expect(row({ className: "flex items-center" }).filter((c) => c.startsWith("gap-"))).toEqual([]);
    expect(stack({ className: "flex flex-col items-start" }).filter((c) => c.startsWith("gap-"))).toEqual([]);
  });
  it("keeps the defaults for an authored row and stack", () => {
    expect(row({})).toContain("flex-wrap");
    expect(row({}).some((c) => c.startsWith("gap-"))).toBe(true);
    expect(stack({}).some((c) => c.startsWith("gap-"))).toBe(true);
  });
});
