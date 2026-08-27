import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DescriptionList } from "../src/components/DescriptionList/DescriptionList";

describe("DescriptionList — resilient rendering", () => {
  it("renders nothing (no throw) when items is undefined", () => {
    const { container } = render(
      <DescriptionList items={undefined as unknown as never} />
    );
    expect(container.querySelector("[data-description-list]")).toBeTruthy();
  });

  it("does not throw when items is not an array (unresolved binding string)", () => {
    const { container } = render(
      <DescriptionList items={"{{candidate.rows}}" as unknown as never} />
    );
    // Falls back to an empty list rather than crashing on .map
    expect(container.querySelector("[data-description-list]")).toBeTruthy();
  });

  it("renders an empty array without throwing", () => {
    const { container } = render(<DescriptionList items={[]} />);
    expect(container.querySelector("[data-description-list]")).toBeTruthy();
  });

  it("coerces non-primitive term/description (jsonb object/array/Date/number) instead of throwing", () => {
    const items = [
      { term: "Parsed CV", description: { skills: ["swim"], years: 3 } as unknown as string },
      { term: "Languages", description: ["English", "French"] as unknown as string },
      { term: "Height Cm", description: 182 as unknown as string },
      { term: "DOB", description: new Date("2000-05-01T00:00:00Z") as unknown as string },
      { term: "Missing", description: null as unknown as string },
    ];
    const { container } = render(<DescriptionList items={items} />);
    expect(container.textContent).toContain("swim");
    expect(container.textContent).toContain("182");
    expect(container.textContent).toContain("2000-05-01");
  });

  it("tolerates a null/malformed item entry", () => {
    const items = [null, { term: "Ok", description: "value" }] as unknown as never;
    const { container } = render(<DescriptionList items={items} />);
    expect(container.textContent).toContain("value");
  });
});
