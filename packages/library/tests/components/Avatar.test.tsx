// packages/library/tests/components/Avatar.test.tsx
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Avatar } from "../../src/components/Avatar/Avatar";

describe("Avatar", () => {
  it("renders fallback initials when src absent", () => {
    const { getByText, container } = render(
      <Avatar name="Jane Doe" size="md" />
    );
    expect(getByText("JD")).toBeTruthy();
    expect(container.querySelector("[data-avatar-size='md']")).toBeTruthy();
  });

  it("renders two chars for single-word name", () => {
    const { getByText } = render(<Avatar name="Plato" size="sm" />);
    expect(getByText("PL")).toBeTruthy();
  });

  it("renders two-letter initials for two-word name (John Doe → JD)", () => {
    const { getByText } = render(<Avatar name="John Doe" size="md" />);
    expect(getByText("JD")).toBeTruthy();
  });

  it("renders img when src provided", () => {
    const { container } = render(
      <Avatar name="Jane Doe" size="md" src="/jane.png" />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe("/jane.png");
    expect(img.getAttribute("alt")).toBe("Jane Doe");
  });

  it("emits status data attribute when status set", () => {
    const { container } = render(
      <Avatar name="J" size="md" status="online" />
    );
    expect(container.querySelector("[data-avatar-status='online']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Avatar name="J" size="md" style={{ radius: "tokens.radius.full" }} />
    );
    expect((container.firstChild as HTMLElement).style.borderRadius)
      .toBe("var(--token-radius-full)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Avatar name="J" size="md" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});

describe("Avatar photoUrl", () => {
  it("renders img element when photoUrl is set", () => {
    const { container } = render(
      <Avatar name="Jane Doe" size="md" photoUrl="https://example.com/jane.jpg" />
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("https://example.com/jane.jpg");
    expect(img!.getAttribute("alt")).toBe("Jane Doe");
  });

  it("renders initials when photoUrl is absent", () => {
    const { container, getByText } = render(<Avatar name="Jane Doe" size="md" />);
    expect(container.querySelector("img")).toBeNull();
    expect(getByText("JD")).toBeTruthy();
  });

  it("falls back to initials on image load error", () => {
    const { container, getByText, queryByText } = render(
      <Avatar name="Jane Doe" size="md" photoUrl="https://example.com/broken.jpg" />
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    // Initials are not visible yet
    expect(queryByText("JD")).toBeNull();
    // Trigger error
    fireEvent.error(img!);
    // Now initials should show
    expect(getByText("JD")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("img has loading=lazy for off-screen perf", () => {
    const { container } = render(
      <Avatar name="Jane Doe" size="md" photoUrl="https://example.com/jane.jpg" />
    );
    const img = container.querySelector("img");
    expect(img!.getAttribute("loading")).toBe("lazy");
  });
});
