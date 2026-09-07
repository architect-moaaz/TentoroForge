/**
 * Regression tests for the display-audit round-5 component fixes.
 *
 * One test per behavioural fix, keyed to the finding it closes:
 *   display 17 — ResourceTimeline runs its StyleSlot through resolveStyle
 *   display 18 — ValidationChecklist honours `className`
 *   display 19 — Gauge/Heatmap/Schematic/SplitArc/Stepper honour `className`
 *   display 20 — FadeIn/Stagger keep their StyleSlot at motionLevel "none"
 *   display 21 — Tag.variant accepts "accent"
 *
 * (display 12 — Dialog's provider-less inline fallback — lives in Dialog.test.tsx.)
 */
import * as React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { TokensProvider } from "../../src/theme/tokens-context";
import { ResourceTimeline } from "../../src/components/ResourceTimeline/ResourceTimeline";
import { ValidationChecklist } from "../../src/components/ValidationChecklist/ValidationChecklist";
import { Gauge } from "../../src/components/Gauge/Gauge";
import { Heatmap } from "../../src/components/Heatmap/Heatmap";
import { Schematic } from "../../src/components/Schematic/Schematic";
import { SplitArc } from "../../src/components/SplitArc/SplitArc";
import { Stepper } from "../../src/components/Stepper/Stepper";
import { FadeIn } from "../../src/components/FadeIn/FadeIn";
import { Stagger } from "../../src/components/Stagger/Stagger";
import { Tag } from "../../src/components/Tag/Tag";
import { TagProps } from "../../src/components/Tag/Tag.schema";

const SLOT = { background: "color.primary.500", padding: "spacing.8" } as any;

// ── display 17 ──────────────────────────────────────────────────────────────
describe("display 17 — ResourceTimeline resolves its StyleSlot", () => {
  it("resolves token refs on the populated root instead of spreading raw", () => {
    const { container } = render(
      <ResourceTimeline
        resources={[{ id: "r1", name: "Room 1" }] as any}
        items={[] as any}
        style={SLOT}
      />,
    );
    const root = container.querySelector("[data-resource-timeline]") as HTMLElement;
    expect(root.style.background).toBe("var(--token-color-primary-500)");
    expect(root.style.padding).toBe("var(--token-spacing-8)");
    // `motion` must not leak through as a bogus CSS property.
    expect(root.getAttribute("style")).not.toContain("motion:");
  });

  it("resolves token refs on the empty-state root too", () => {
    const { container } = render(
      <ResourceTimeline resources={[] as any} items={[] as any} style={SLOT} />,
    );
    const root = container.querySelector("[data-timeline-empty]") as HTMLElement;
    expect(root.style.background).toBe("var(--token-color-primary-500)");
    expect(root.style.padding).toBe("var(--token-spacing-8)");
  });

  it("emits data-motion from style.motion", () => {
    const { container } = render(
      <ResourceTimeline
        resources={[{ id: "r1", name: "Room 1" }] as any}
        items={[] as any}
        style={{ motion: "fade-in" } as any}
      />,
    );
    const root = container.querySelector("[data-resource-timeline]") as HTMLElement;
    expect(root.getAttribute("data-motion")).toBe("fade-in");
  });
});

// ── display 18 / 19 ─────────────────────────────────────────────────────────
describe("display 18/19 — declared className reaches the root element", () => {
  it("ValidationChecklist keeps its layout class and adds className", () => {
    const { container } = render(
      <ValidationChecklist items={[{ label: "Has a SKU", valid: true }]} className="mt-4" />,
    );
    const root = container.querySelector("[data-validation-checklist]") as HTMLElement;
    expect(root.className).toContain("flex flex-col gap-2");
    expect(root.className).toContain("mt-4");
  });

  it("Gauge", () => {
    const { container } = render(<Gauge value={40} className="mt-4" />);
    const root = container.querySelector("[data-gauge]") as HTMLElement;
    expect(root.className).toContain("inline-flex");
    expect(root.className).toContain("mt-4");
  });

  it("Heatmap — both the populated root and the empty placeholder", () => {
    const populated = render(
      <Heatmap data={[{ x: "Mon", y: "A", value: 3 }] as any} className="mt-4" />,
    );
    const root = populated.container.querySelector("[data-heatmap]") as HTMLElement;
    expect(root.className).toContain("inline-block");
    expect(root.className).toContain("mt-4");

    const empty = render(<Heatmap data={[] as any} className="mt-4" />);
    const ph = empty.container.querySelector("[data-heatmap-placeholder]") as HTMLElement;
    expect(ph.className).toContain("mt-4");
  });

  it("Schematic", () => {
    const { container } = render(<Schematic markers={[] as any} className="mt-4" />);
    const root = container.querySelector("[data-schematic]") as HTMLElement;
    expect(root.className).toContain("w-full");
    expect(root.className).toContain("mt-4");
  });

  it("SplitArc", () => {
    const { container } = render(
      <SplitArc segments={[{ value: 62, color: "#2563eb" }] as any} className="mt-4" />,
    );
    const root = container.querySelector("[data-splitarc]") as HTMLElement;
    expect(root.className).toContain("inline-flex");
    expect(root.className).toContain("mt-4");
  });

  it("Stepper", () => {
    const { container } = render(
      <Stepper steps={[{ id: "a", label: "One" }] as any} className="mt-4" />,
    );
    const root = container.querySelector("[data-stepper]") as HTMLElement;
    expect(root.className).toContain("flex items-start");
    expect(root.className).toContain("mt-4");
  });
});

// ── display 20 ──────────────────────────────────────────────────────────────
describe("display 20 — FadeIn/Stagger keep their StyleSlot when motion is off", () => {
  const noMotion = (ui: React.ReactElement) =>
    render(<TokensProvider tokens={{ motionLevel: "none" } as any}>{ui}</TokensProvider>);

  it("FadeIn still applies background + padding at motionLevel none", () => {
    const { container } = noMotion(
      <FadeIn style={SLOT}>
        <span>x</span>
      </FadeIn>,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.tagName).toBe("DIV");
    expect(root.style.background).toBe("var(--token-color-primary-500)");
    expect(root.style.padding).toBe("var(--token-spacing-8)");
    // …and it must NOT animate.
    expect(root.className).not.toContain("motion-wrapper");
    expect(root.getAttribute("data-motion")).toBeNull();
    expect(root.style.getPropertyValue("--fadein-duration")).toBe("");
    expect(root.textContent).toBe("x");
  });

  it("Stagger still applies background + padding at motionLevel none", () => {
    const { container } = noMotion(
      <Stagger style={SLOT}>
        <span>a</span>
        <span>b</span>
      </Stagger>,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.style.background).toBe("var(--token-color-primary-500)");
    expect(root.style.padding).toBe("var(--token-spacing-8)");
    expect(root.className).not.toContain("motion-wrapper");
    expect(root.getAttribute("data-motion")).toBeNull();
    expect(root.querySelector(".motion-stagger-item")).toBeNull();
    expect(root.textContent).toBe("ab");
  });
});

// ── display 21 ──────────────────────────────────────────────────────────────
describe("display 21 — Tag.variant accepts accent", () => {
  it("parses through the Zod schema", () => {
    expect(TagProps.parse({ label: "New", variant: "accent" }).variant).toBe("accent");
  });

  it("renders the accent classes", () => {
    const { container } = render(<Tag label="New" variant="accent" />);
    const root = container.querySelector("[data-tag]") as HTMLElement;
    expect(root.className).toContain("bg-accent");
    expect(root.className).toContain("text-accent-foreground");
  });
});
