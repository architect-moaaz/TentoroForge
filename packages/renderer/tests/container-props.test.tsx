/**
 * Container — the registry has always advertised
 * direction / gap / padding / align / justify / wrap alongside maxWidth, and
 * until this suite existed the node read only maxWidth: probe_props_5 in
 * docs/editor-audit/panels.md set all six and the element still rendered as
 * `class="mx-auto w-full px-4 sm:px-6 lg:px-8 max-w-screen-sm"`.
 *
 * Spacer is here for the same reason: its registry enum resolved through
 * `tokenToCssVar` to `var(--token-md)`, which compileTokens defines as a
 * BOX-SHADOW, so a dropped Spacer had no size at all.
 */
import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

const ctx = { data: {}, slots: {}, layouts: {} } as any;

function container(props: Record<string, unknown>): string {
  return renderToString(
    renderNode({ id: "c", type: "Container", props, children: [] } as any, ctx),
  );
}

describe("Container renderer — advertised props", () => {
  it("honours every prop probe_props_5 proved inert", () => {
    const html = container({
      direction: "horizontal", gap: "xl", padding: "xl",
      align: "center", justify: "between", wrap: true, maxWidth: "sm",
    });
    expect(html).toContain("flex");
    expect(html).toContain("md:flex-row");
    expect(html).toContain("gap-8");
    expect(html).toContain("p-8");
    expect(html).toContain("items-center");
    expect(html).toContain("justify-between");
    expect(html).toContain("flex-wrap");
    expect(html).toContain("max-w-screen-sm");
  });

  it("maps justify:evenly, which only Container offers", () => {
    expect(container({ justify: "evenly" })).toContain("justify-evenly");
  });

  it("leaves a maxWidth-only Container as the plain centred block it was", () => {
    // Every schema written before the props were wired up looks like this, and
    // turning those into flex boxes with a default gap would silently re-space
    // every page already on disk.
    const html = container({ maxWidth: "lg" });
    expect(html).toContain("mx-auto w-full px-4 sm:px-6 lg:px-8 max-w-screen-lg");
    expect(html).not.toContain("flex");
    expect(html).not.toContain("gap-");
  });

  it("replaces the responsive gutter when padding is set, rather than stacking", () => {
    // `p-4` and `px-4` have equal specificity, so emitting both would leave the
    // horizontal padding to Tailwind's output order instead of to the user.
    const html = container({ padding: "sm" });
    expect(html).toContain("p-2");
    expect(html).not.toContain("px-4");
  });

  it("still treats a caller className as a styled passthrough box", () => {
    const html = container({ className: "size-[56px]", gap: "md", maxWidth: "sm" });
    expect(html).toContain('class="size-[56px]"');
    expect(html).not.toContain("max-w-screen-sm");
  });
});

describe("Spacer renderer — registry enum sizes", () => {
  it("resolves the enum through the spacing scale, not --token-md", () => {
    const html = renderToString(
      renderNode({ id: "sp", type: "Spacer", props: { size: "md" } } as any, ctx),
    );
    expect(html).toContain("--token-spacing-4");
    expect(html).not.toContain("var(--token-md)");
  });

  it("keeps dotted token refs working", () => {
    const html = renderToString(
      renderNode({ id: "sp", type: "Spacer", props: { size: "spacing.6" } } as any, ctx),
    );
    expect(html).toContain("--token-spacing-6");
  });

  it("passes a literal CSS length through untouched", () => {
    const html = renderToString(
      renderNode({ id: "sp", type: "Spacer", props: { size: "12px" } } as any, ctx),
    );
    expect(html).toContain("height:12px");
  });
});
