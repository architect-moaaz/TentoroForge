import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Section } from "../src/components/Section/Section";

describe("a headline section is the page header", () => {
  it("puts the title in an h1 and the actions beside it", () => {
    const { container } = render(
      <Section role="headline" title="Refund Cases" subtitle="Every case across the group">
        <button>New Refund Case</button>
      </Section>,
    );
    const h1 = container.querySelector("h1");
    expect(h1?.textContent).toBe("Refund Cases");
    expect(h1?.className).toContain("font-semibold");
    expect(container.querySelector("[data-section-actions] button")?.textContent).toBe("New Refund Case");
  });
  it("keeps a plain section's title as an h2 with the body below", () => {
    const { container } = render(<Section title="Details"><p>body</p></Section>);
    expect(container.querySelector("h2")?.textContent).toBe("Details");
    expect(container.querySelector("[data-section-actions]")).toBeNull();
  });
});
