import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Cluster } from "../../src/components/Cluster/Cluster";

describe("Cluster", () => {
  it("renders children and emits justify/align data attributes", () => {
    const { container, getByText } = render(
      <Cluster justify="between" align="end">
        <span>a</span><span>b</span>
      </Cluster>
    );
    expect(getByText("a")).toBeTruthy();
    expect(getByText("b")).toBeTruthy();
    expect(container.querySelector("[data-cluster-justify='between']")).toBeTruthy();
    expect(container.querySelector("[data-cluster-align='end']")).toBeTruthy();
  });

  it("applies gap as CSS custom property when set", () => {
    const { container } = render(
      <Cluster justify="start" align="center" gap="tokens.spacing.4">
        <span>a</span>
      </Cluster>
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.gap).toBe("var(--token-spacing-4)");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Cluster justify="start" align="center" style={{ padding: "tokens.spacing.6" }}>
        <span>a</span>
      </Cluster>
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-6)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Cluster justify="start" align="center" style={{ motion: "fade-up" }}>
        <span>a</span>
      </Cluster>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-up");
  });

  // Codifies the iteration-3 v4 spike CSS fix. Default Cluster uses flex +
  // flex-wrap + justify-between, which gives content-sized children — KPI
  // tile rows visually shrink to fit their labels and look uneven. With
  // equalCols the component switches to CSS grid with N equal-width columns
  // using minmax(0, 1fr), giving true equal-width distribution.
  describe("equalCols (v4 spike CSS fix)", () => {
    it("switches to CSS grid with repeat(N, minmax(0, 1fr)) when equalCols is true", () => {
      const { container } = render(
        <Cluster justify="start" align="center" equalCols>
          <span>a</span><span>b</span><span>c</span>
        </Cluster>
      );
      const root = container.firstChild as HTMLElement;
      expect(root.style.display).toBe("grid");
      expect(root.style.gridTemplateColumns).toBe("repeat(3, minmax(0, 1fr))");
      expect(root.getAttribute("data-cluster-equal-cols")).toBe("true");
    });

    it("applies grid-auto-rows: 1fr only when equalRows is also set", () => {
      const { container: c1 } = render(
        <Cluster equalCols><span>a</span><span>b</span></Cluster>
      );
      expect((c1.firstChild as HTMLElement).style.gridAutoRows).toBe("");

      const { container: c2 } = render(
        <Cluster equalCols equalRows><span>a</span><span>b</span></Cluster>
      );
      expect((c2.firstChild as HTMLElement).style.gridAutoRows).toBe("1fr");
    });

    it("keeps default flex behaviour when equalCols is absent", () => {
      const { container } = render(
        <Cluster justify="start" align="center">
          <span>a</span>
        </Cluster>
      );
      const root = container.firstChild as HTMLElement;
      expect(root.style.display).toBe("");
      expect(root.className).toContain("flex");
      expect(root.className).toContain("flex-wrap");
    });
  });
});
