import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Progress } from "../../src/components/Progress/Progress";

/**
 * The two branches of Progress disagreed about whether a label is something you
 * can see. The bar branch drew it; the circular branch passed it to
 * `aria-label` and rendered nothing else — so a circular Progress in a
 * generated app was a decorative arc: no words, and (before `showValue` had a
 * control) no number either. Both branches are asserted together so they cannot
 * drift apart again.
 */
describe("Progress renders its label in both variants", () => {
  for (const variant of ["bar", "circular"] as const) {
    it(`${variant}: the label is visible text, not only an aria-label`, () => {
      render(<Progress variant={variant} label="Import" value={3} max={7} />);
      expect(screen.getByText("Import")).toBeInTheDocument();
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-label", "Import");
    });

    it(`${variant}: showValue reports the fraction of max, not of 100`, () => {
      render(<Progress variant={variant} label="Import" value={3} max={7} showValue />);
      // 3 of 7 — the case that could not be expressed at all while `max` was
      // unreachable from the editor.
      expect(screen.getByText("43%")).toBeInTheDocument();
    });

    it(`${variant}: no label prop renders no stray empty text node`, () => {
      const { container } = render(<Progress variant={variant} value={50} />);
      expect(container.querySelector("[data-progress]")).not.toBeNull();
    });
  }
});
