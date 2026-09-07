import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DesignTimeProvider } from "../../src/util/designTime";
import { PresenceIndicator } from "../../src/components/PresenceIndicator/PresenceIndicator";
import { UndoManager } from "../../src/components/UndoManager/UndoManager";
import { TourOverlay } from "../../src/components/TourOverlay/TourOverlay";

/**
 * ONE FILE FOR ONE SHARED DEFECT.
 *
 * PresenceIndicator, UndoManager and TourOverlay are all fed by a runtime the
 * editor canvas does not run, and all three ended in `return null`. Three audit
 * entries reported it as three bugs: "renders absolutely nothing on the canvas,
 * and gets no empty-node hint either — invisible AND undiagnosable".
 *
 * The two halves are asserted together on purpose, because either one alone is
 * a regression waiting to happen:
 *   - WITHOUT a design-time provider the render must still be empty. A toast
 *     bar that draws a dashed box in a shipped app is a worse bug than the one
 *     being fixed.
 *   - WITH one, the node must produce a real element the canvas can find,
 *     measure and select.
 *
 * Assertions are on a measurable box (`data-design-time-placeholder`), never on
 * "something rendered": the original bug produced a wrapper element too — it
 * just had no content and no area.
 */

const CASES: Array<[string, () => React.ReactElement]> = [
  ["PresenceIndicator", () => <PresenceIndicator />],
  ["UndoManager", () => <UndoManager />],
  ["TourOverlay", () => <TourOverlay steps={[]} />],
];

describe("runtime-fed components on an authoring surface", () => {
  for (const [name, node] of CASES) {
    it(`${name} renders nothing when no design-time provider is mounted`, () => {
      const { container } = render(node());
      expect(container.querySelector("[data-design-time-placeholder]")).toBeNull();
      expect(container.textContent).toBe("");
    });

    it(`${name} renders a selectable, named placeholder inside a design-time surface`, () => {
      const { container } = render(<DesignTimeProvider>{node()}</DesignTimeProvider>);
      const box = container.querySelector<HTMLElement>(
        "[data-design-time-placeholder]",
      );
      expect(box).not.toBeNull();
      // It must say WHICH component it is — the whole complaint was that the
      // author could not tell what the invisible node was.
      expect(box!.getAttribute("data-design-time-placeholder")).toBe(name);
      expect(box!.textContent).toContain(name);
      // Scaffolding for the author, not content for a screen reader.
      expect(box!.getAttribute("aria-hidden")).toBe("true");
      // A box, not a zero-area wrapper: the original defect was `display:
      // contents` with a 0x0 rect and nothing for the hint overlay to attach to.
      expect(box!.style.display).toBe("inline-flex");
      expect(parseInt(box!.style.minHeight, 10)).toBeGreaterThan(0);
      expect(parseInt(box!.style.minWidth, 10)).toBeGreaterThan(0);
    });
  }

  it("an explicit value={false} opts a nested subtree back out", () => {
    const { container } = render(
      <DesignTimeProvider>
        <DesignTimeProvider value={false}>
          <UndoManager />
        </DesignTimeProvider>
      </DesignTimeProvider>,
    );
    expect(container.querySelector("[data-design-time-placeholder]")).toBeNull();
  });

  it("real data still wins over the placeholder inside a design-time surface", () => {
    const { container } = render(
      <DesignTimeProvider>
        <PresenceIndicator users={[{ userId: "u1", name: "Ada Lovelace" }]} />
      </DesignTimeProvider>,
    );
    expect(container.querySelector("[data-design-time-placeholder]")).toBeNull();
    expect(container.querySelector("[data-forge-presence]")).not.toBeNull();
  });
});
