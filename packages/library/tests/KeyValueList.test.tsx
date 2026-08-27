import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { KeyValueList } from "../src/components/KeyValueList/KeyValueList";

describe("KeyValueList — value coercion", () => {
  it("renders non-string values (Date/number/null) without throwing", () => {
    const items = [
      { label: "Joined", value: new Date("2025-01-20T00:00:00Z") as unknown as string },
      { label: "Count", value: 5 as unknown as string },
      { label: "Missing", value: null as unknown as string },
    ];
    const { container } = render(<KeyValueList items={items} />);
    expect(container.textContent).toContain("2025-01-20");
    expect(container.textContent).toContain("5");
  });
});
