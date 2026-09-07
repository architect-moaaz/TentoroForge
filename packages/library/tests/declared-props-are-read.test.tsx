import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Tooltip } from "../src/components/Tooltip/Tooltip";
import { Popover } from "../src/components/Popover/Popover";
import { HoverCard } from "../src/components/HoverCard/HoverCard";
import { Drawer } from "../src/components/Drawer/Drawer";
import { DataGrid } from "../src/components/DataGrid/DataGrid";
import { Timeline } from "../src/components/Timeline/Timeline";
import { OptimisticProvider } from "../src/components/OptimisticProvider/OptimisticProvider";
import { TableSortable } from "../src/components/Table/TableSortable";

/**
 * A PROP THE SCHEMA DECLARES AND THE COMPONENT DROPS IS A LIE IN THE CONTRACT.
 *
 * Eight components declared `className` (and three of them `style`) in their Zod
 * schema and their node schema, and destructured neither. A producer — the Figma
 * mapper puts Tailwind on every node — writing `props.className` had it silently
 * discarded on all eight, and nothing anywhere reported it.
 *
 * Swept together rather than eight separate cases, because eight separate cases
 * is how eight components ended up with the same hole. The assertion is that the
 * authored class REACHES the DOM, not that the component rendered.
 */

const AUTHORED = "authored-utility-class";

const CASES: Array<[string, () => React.ReactElement]> = [
  ["Tooltip", () => <Tooltip label="t" content="c" className={AUTHORED} />],
  ["Popover", () => <Popover trigger="t" content="c" className={AUTHORED} />],
  ["HoverCard", () => <HoverCard label="t" content="c" className={AUTHORED} />],
  ["Drawer", () => <Drawer trigger="t" content="c" className={AUTHORED} />],
  ["DataGrid", () => (
    <DataGrid columns={[{ key: "a", label: "A" }] as any} rows={[]} className={AUTHORED} />
  )],
  ["Timeline", () => (
    <Timeline entries={[{ timestamp: "2026-01-01", title: "x" }] as any} className={AUTHORED} />
  )],
  ["OptimisticProvider", () => (
    <OptimisticProvider className={AUTHORED}><span>x</span></OptimisticProvider>
  )],
  ["TableSortable", () => (
    <TableSortable columns={[{ key: "a", label: "A" }] as any} className={AUTHORED} />
  )],
];

describe("className declared in the schema reaches the DOM", () => {
  for (const [name, node] of CASES) {
    it(name, () => {
      const { container } = render(node());
      expect(
        container.querySelector(`.${AUTHORED}`),
        `${name} declares className and dropped it`,
      ).not.toBeNull();
    });
  }

  it("does not clobber the component's own classes", () => {
    const { container } = render(<Popover trigger="t" content="c" className={AUTHORED} />);
    const trigger = container.querySelector("[data-popover]")!;
    expect(trigger.className).toContain("inline-flex");
    // The authored class comes LAST so it wins on a conflicting utility, which
    // is the reason a producer sets it at all.
    expect(trigger.className.trim().endsWith(AUTHORED)).toBe(true);
  });
});

describe("style declared in the schema reaches the DOM", () => {
  it("OptimisticProvider merges it over the display:contents it needs", () => {
    const { container } = render(
      <OptimisticProvider style={{ opacity: "0.5" } as any}><span>x</span></OptimisticProvider>,
    );
    const el = container.querySelector<HTMLElement>("[data-forge-optimistic]")!;
    expect(el.style.opacity).toBe("0.5");
    expect(el.style.display).toBe("contents");
  });

  it("Timeline applies it to the list root", () => {
    const { container } = render(
      <Timeline entries={[{ timestamp: "2026-01-01", title: "x" }] as any} style={{ opacity: "0.5" } as any} />,
    );
    expect(container.querySelector<HTMLElement>("ol")!.style.opacity).toBe("0.5");
  });
});
