import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import * as React from "react";
import { renderNode, type DispatchContext } from "../src/runtime/dispatch";

const ctx: DispatchContext = { data: {} } as any;

describe("dispatch v2 — StyleSlot resolution", () => {
  it("applies StyleSlot.padding to Stack", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s",
          type: "Stack",
          props: { gap: "md" },
          children: [],
          style: { padding: "tokens.spacing.semantic.section" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("padding:var(--token-spacing-semantic-section)");
  });

  it("applies StyleSlot.padding to Row", () => {
    const html = renderToString(
      renderNode(
        {
          id: "r",
          type: "Row",
          props: {},
          children: [],
          style: { padding: "tokens.spacing.4" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("padding:var(--token-spacing-4)");
  });

  it("applies StyleSlot.radius + shadow to Grid", () => {
    const html = renderToString(
      renderNode(
        {
          id: "g",
          type: "Grid",
          props: { columns: 2 },
          children: [],
          style: {
            radius: "tokens.radius.md",
            shadow: "tokens.shadow.card",
          },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("border-radius:var(--token-radius-md)");
    expect(html).toContain("box-shadow:var(--token-shadow-card)");
  });

  it("applies solid background to Container", () => {
    const html = renderToString(
      renderNode(
        {
          id: "ct",
          type: "Container",
          props: {},
          children: [],
          style: {
            background: { type: "solid", value: "tokens.color.brand.500" },
          },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("background:var(--token-color-brand-500)");
  });

  it("applies gradient background to Box", () => {
    const html = renderToString(
      renderNode(
        {
          id: "bx",
          type: "Box",
          props: {},
          children: [],
          style: {
            background: {
              type: "gradient",
              from: "tokens.color.brand.400",
              to: "tokens.color.brand.600",
              angle: 90,
            },
          },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain(
      "background:linear-gradient(90deg, var(--token-color-brand-400) 0%, var(--token-color-brand-600) 100%)"
    );
  });

  it("emits data-motion on Box when motion set", () => {
    const html = renderToString(
      renderNode(
        {
          id: "b",
          type: "Box",
          props: {},
          children: [],
          style: { motion: "fade-in" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain('data-motion="fade-in"');
  });

  it("emits data-motion on Stack", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s2",
          type: "Stack",
          props: {},
          children: [],
          style: { motion: "fade-up" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain('data-motion="fade-up"');
  });

  it("does NOT emit data-motion when motion is absent", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s3",
          type: "Stack",
          props: {},
          children: [],
          style: { padding: "tokens.spacing.4" },
        } as any,
        ctx
      ) as any
    );
    expect(html).not.toContain("data-motion");
  });

  it("does NOT emit data-motion when motion is 'none'", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s4",
          type: "Stack",
          props: {},
          children: [],
          style: { motion: "none" },
        } as any,
        ctx
      ) as any
    );
    expect(html).not.toContain("data-motion=");
  });
});

describe("dispatch v2 — Custom node", () => {
  it("renders Custom node HTML content", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c",
          type: "Custom",
          props: { html: "<p>safe content</p>" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("<p>safe content</p>");
  });

  it("strips <script> tags from Custom node html", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c2",
          type: "Custom",
          props: { html: "<p>safe</p><script>alert(1)</script>" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("<p>safe</p>");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("alert(1)");
  });

  it("strips on* event handlers from Custom node html", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c3",
          type: "Custom",
          props: { html: '<button onclick="evil()">click</button>' },
        } as any,
        ctx
      ) as any
    );
    expect(html).not.toContain("onclick");
    expect(html).not.toContain("evil()");
  });

  it("renders Custom node with custom-block class", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c4",
          type: "Custom",
          props: { html: "<p>x</p>", tailwind: "p-4 bg-white" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain('class="custom-block p-4 bg-white"');
  });

  it("applies StyleSlot to Custom node", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c5",
          type: "Custom",
          props: { html: "<p>x</p>" },
          style: { padding: "tokens.spacing.4", motion: "slide-in" },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("padding:var(--token-spacing-4)");
    expect(html).toContain('data-motion="slide-in"');
  });

  it("Custom node sanitizes namespace XSS bypasses (svg/script)", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c",
          type: "Custom",
          props: { html: "<svg><script>alert(1)</script></svg>" },
        } as any,
        ctx
      ) as any
    );
    // dompurify strips script tags inside SVG; regex sanitizers often miss this
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("alert");
  });

  it("Custom node sanitizes data: URL XSS in href", () => {
    const html = renderToString(
      renderNode(
        {
          id: "c",
          type: "Custom",
          props: {
            html: '<a href="data:text/html,<script>alert(1)</script>">x</a>',
          },
        } as any,
        ctx
      ) as any
    );
    // dompurify strips dangerous URL schemes by default
    expect(html).not.toContain("data:text/html");
  });
});

describe("dispatch v2 — v1 schema backward compatibility", () => {
  it("v1 Stack (no style field) renders without data-motion", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s",
          type: "Stack",
          props: { direction: "vertical", gap: "spacing.4" },
          children: [],
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain('class="flex flex-col');
    expect(html).toContain("var(--token-spacing-4)");
    expect(html).not.toContain("data-motion=");
  });

  it("v1 Box with old-style flat style still renders", () => {
    const html = renderToString(
      renderNode(
        {
          id: "b",
          type: "Box",
          style: { padding: "spacing.4" },
          children: [],
        } as any,
        ctx
      ) as any
    );
    // tokens.ts resolveStyle handles flat string style
    expect(html).toContain("var(--token-spacing-4)");
  });

  it("v2 node with style: undefined renders same as v1 with no style", () => {
    const v1 = { id: "s", type: "Stack", props: { gap: "md" }, children: [] };
    const v2 = { ...v1, style: undefined };
    const v1Html = renderToString(renderNode(v1 as any, ctx) as any);
    const v2Html = renderToString(renderNode(v2 as any, ctx) as any);
    expect(v1Html).toBe(v2Html);
  });
});
