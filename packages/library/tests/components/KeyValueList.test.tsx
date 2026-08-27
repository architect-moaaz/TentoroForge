// packages/library/tests/components/KeyValueList.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { KeyValueList } from "../../src/components/KeyValueList/KeyValueList";

describe("KeyValueList", () => {
  it("renders dl/dt/dd structure for items", () => {
    const { container, getByText } = render(
      <KeyValueList items={[
        { label: "Email", value: "x@y.com" },
        { label: "Role", value: "Admin" },
      ]} />
    );
    expect(container.querySelector("dl")).toBeTruthy();
    expect(container.querySelectorAll("dt").length).toBe(2);
    expect(container.querySelectorAll("dd").length).toBe(2);
    expect(getByText("Email")).toBeTruthy();
    expect(getByText("x@y.com")).toBeTruthy();
  });

  it("renders empty value as dash", () => {
    const { container } = render(
      <KeyValueList items={[{ label: "Last login", value: "" }]} />
    );
    const dd = container.querySelector("dd") as HTMLElement;
    expect(dd.textContent).toContain("—");
  });

  it("emits copy button when copyable: true", () => {
    const { container } = render(
      <KeyValueList items={[{ label: "ID", value: "abc-123", copyable: true }]} />
    );
    expect(container.querySelector("button[aria-label^='Copy']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <KeyValueList items={[{ label: "X", value: "y" }]}
        style={{ padding: "tokens.spacing.4" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <KeyValueList items={[{ label: "X", value: "y" }]}
        style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
