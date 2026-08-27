import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Badge } from "../src/components/Badge/Badge";

describe("Badge — content coercion", () => {
  // Bound rows routinely pass a numeric field (a count, a numeric status) as
  // `content`. _inferVariant used to call `.toLowerCase()` on it and threw
  // "(content || '').toLowerCase is not a function", crashing the whole page.
  it("renders a numeric content without throwing", () => {
    expect(() => render(<Badge content={5 as unknown as string} />)).not.toThrow();
  });

  it("renders null/undefined content without throwing", () => {
    expect(() => render(<Badge content={null as unknown as string} />)).not.toThrow();
    expect(() => render(<Badge content={undefined as unknown as string} />)).not.toThrow();
  });

  it("still infers a variant for a known string status", () => {
    const { container } = render(<Badge content="Approved" />);
    expect(container.textContent).toContain("Approved");
  });
});

describe("Badge — Date content (formatValue path)", () => {
  it("renders a Date object without throwing and shows an ISO date", () => {
    const { container } = render(<Badge content={new Date("2025-01-20T00:00:00Z") as unknown as string} />);
    expect(container.textContent).toContain("2025-01-20");
  });
});
