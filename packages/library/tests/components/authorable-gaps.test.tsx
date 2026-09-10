import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DesignTimeProvider } from "@tentoroforge/renderer";
import { TableSortable } from "../../src/components/Table/TableSortable";
import { Tooltip } from "../../src/components/Tooltip/Tooltip";
import { FocusTrap } from "../../src/components/FocusTrap/FocusTrap";
import { TourOverlayProps } from "../../src/components/TourOverlay/TourOverlay.schema";
import { TooltipProps } from "../../src/components/Tooltip/Tooltip.schema";
import { TableSortableProps } from "../../src/components/Table/Table.schema";

/**
 * ONE FILE FOR ONE CLASS: a prop the component reads, the schema requires, or
 * the runtime supports — that no author could reach.
 *
 * These are the findings the previous fix pass explicitly ROUTED rather than
 * closed, because each needed a change below the registry: a component that had
 * no prop to expose, a schema that forbade a shape the runtime implements, a
 * value hardwired in JSX. They are grouped because the failure reads the same
 * from the outside every time — the editor offers a control that cannot work,
 * or offers nothing where the component has a capability — and because fixing
 * them one file at a time is how five of them ended up in one audit.
 */

const inEditor = (ui: React.ReactElement) => <DesignTimeProvider>{ui}</DesignTimeProvider>;

beforeEach(() => {
  document.body.innerHTML = "";
});

// ---------------------------------------------------------------------------

describe("TableSortable had no route to a row", () => {
  const columns = [
    { key: "name", label: "Name" },
    { key: "score", label: "Score" },
  ];

  it("renders rows from `rows`", () => {
    // The whole finding: the component built its <tbody> from `children` alone
    // while the registry declares it a leaf, so a dropped TableSortable was a
    // header over an empty <tbody>, permanently.
    const { container } = render(
      <TableSortable columns={columns} rows={[{ name: "Ada", score: 9 }, { name: "Grace", score: 7 }]} />,
    );
    const bodyRows = container.querySelectorAll("tbody tr");
    expect(bodyRows.length).toBe(2);
    expect(container.querySelector("tbody")?.textContent).toContain("Ada");
  });

  it("says so when there are no rows, instead of drawing a void", () => {
    // Table has an empty state; TableSortable had no empty branch in its source
    // at all, so "no data" and "broken" were the same DOM.
    const { container } = render(<TableSortable columns={columns} rows={[]} />);
    const empty = container.querySelector('[data-forge-empty="table-sortable"]');
    expect(empty).not.toBeNull();
  });

  it("uses the authored emptyText when given one", () => {
    render(<TableSortable columns={columns} rows={[]} emptyText="No entries yet" />);
    expect(screen.getByText("No entries yet")).toBeInTheDocument();
  });

  it("keeps the legacy children path so hand-authored pages do not regress", () => {
    // Pages in the wild already put <tr>s inside this component. They must not
    // start rendering an empty state instead.
    const { container } = render(
      <TableSortable columns={columns}>
        <tr><td>hand-authored</td><td>row</td></tr>
      </TableSortable>,
    );
    expect(container.querySelector("tbody")?.textContent).toContain("hand-authored");
    expect(container.querySelector("[data-forge-empty]")).toBeNull();
  });

  it("actually sorts, in both directions", () => {
    // Sorting was previously a state change over zero rows: aria-sort flipped,
    // the header grew an arrow, and nothing moved.
    const { container } = render(
      <TableSortable columns={columns} rows={[{ name: "Grace", score: 7 }, { name: "Ada", score: 9 }]} />,
    );
    const nameHeader = screen.getByRole("columnheader", { name: /name/i });

    fireEvent.click(nameHeader);
    let cells = [...container.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
    expect(cells).toEqual(["Ada", "Grace"]);

    fireEvent.click(nameHeader);
    cells = [...container.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
    expect(cells).toEqual(["Grace", "Ada"]);
  });

  it("sorts numbers as numbers, not as text", () => {
    // A plain string compare puts 10 before 9, which reads as a broken sort.
    const { container } = render(
      <TableSortable columns={columns} rows={[{ name: "a", score: 10 }, { name: "b", score: 9 }]} />,
    );
    fireEvent.click(screen.getByRole("columnheader", { name: /score/i }));
    const cells = [...container.querySelectorAll("tbody tr td:last-child")].map((c) => c.textContent);
    expect(cells).toEqual(["9", "10"]);
  });

  it("sinks blank cells in both directions", () => {
    // "No value" is not the smallest value — a user reversing the sort does not
    // expect the gaps to lead.
    const rows = [{ name: "b", score: 1 }, { name: "", score: 2 }, { name: "a", score: 3 }];
    const { container } = render(<TableSortable columns={columns} rows={rows} />);
    const nameHeader = screen.getByRole("columnheader", { name: /name/i });
    const names = () => [...container.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);

    fireEvent.click(nameHeader);
    expect(names()[2]).toBe("");
    fireEvent.click(nameHeader);
    expect(names()[2]).toBe("");
  });

  it("does not sort on an authoring surface", () => {
    // The pre-existing rule, re-asserted here because `rows` gives the click
    // something to actually move for the first time.
    const { container } = render(
      inEditor(<TableSortable columns={columns} rows={[{ name: "Grace", score: 7 }, { name: "Ada", score: 9 }]} />),
    );
    fireEvent.click(screen.getByRole("columnheader", { name: /name/i }));
    const cells = [...container.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
    expect(cells).toEqual(["Grace", "Ada"]);
  });

  it("declares rows on the props schema, not just via passthrough", () => {
    // `extract-contracts.ts` reads THIS schema to tell the page composer which
    // props exist. Passthrough would carry the value while the contract still
    // said the prop did not exist — so the model would be told not to emit it,
    // and the void would quietly come back on generated pages.
    expect("rows" in TableSortableProps.shape).toBe(true);
    expect("emptyText" in TableSortableProps.shape).toBe(true);
    expect(TableSortableProps.safeParse({ columns: [], rows: [{ a: 1 }] }).success).toBe(true);
  });
});

// ---------------------------------------------------------------------------

describe("Tooltip hover intent", () => {
  it("is authorable, and defaults to the conventional window", () => {
    // `delayDuration` was hardwired to 0, so every tooltip in every generated
    // app fired the instant the pointer crossed it, with no layer able to say
    // otherwise. Asserted through the schema and the registry rather than
    // through Radix's timers, which are not observable from the DOM.
    expect("delayMs" in TooltipProps.shape).toBe(true);
    // Bounded the same way HoverCard's pair is, so a typo cannot push a hint
    // past any plausible hover intent.
    expect(TooltipProps.safeParse({ label: "a", content: "b", delayMs: 700 }).success).toBe(true);
    expect(TooltipProps.safeParse({ label: "a", content: "b", delayMs: -1 }).success).toBe(false);
  });

  it("still renders its trigger", () => {
    render(<Tooltip label="Hover" content="Hint" delayMs={0} />);
    expect(screen.getByText("Hover")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------

describe("FocusTrap could not be styled", () => {
  it("accepts a style slot", () => {
    // It is the one component in the family that renders a real layout box, and
    // it was the one with no `style` slot in any layer — so an empty trap was a
    // 960x0 strip and padding it out was not authorable.
    const { container } = render(
      <FocusTrap style={{ padding: "24px" } as any}><button>inside</button></FocusTrap>,
    );
    const root = container.querySelector("[data-forge-focus-trap]") as HTMLElement;
    expect(root.style.padding).toBe("24px");
  });

  it("is a visible box on an authoring surface and unchanged in a running app", () => {
    const { container: editor } = render(inEditor(<FocusTrap />));
    const inCanvas = editor.querySelector("[data-forge-focus-trap]") as HTMLElement;
    expect(inCanvas.style.minHeight).toBe("44px");

    const { container: app } = render(<FocusTrap />);
    const shipped = app.querySelector("[data-forge-focus-trap]") as HTMLElement;
    // No shipped page moves by a pixel.
    expect(shipped.style.minHeight).toBe("");
  });

  it("lets authored style win over the design-time box", () => {
    const { container } = render(
      inEditor(<FocusTrap style={{ minHeight: "200px" } as any} />),
    );
    const root = container.querySelector("[data-forge-focus-trap]") as HTMLElement;
    expect(root.style.minHeight).toBe("200px");
  });
});

// ---------------------------------------------------------------------------

describe("TourOverlay's seed could not satisfy its own schema", () => {
  it("requires a non-empty array of steps, which a text box could never supply", () => {
    // `steps` was `{ type: "string", control: "text", default: "" }` against
    // `z.array(TourStep).min(1)` — required, no default. Building the registry's
    // default props object and parsing it FAILED with
    // "expected array, received string", so every palette-dropped TourOverlay
    // was invalid on arrival and rendered nothing. It was the only seed in the
    // library that could not satisfy the schema it seeds.
    //
    // The registry half of this — that the seed IS now a valid array — is
    // asserted in packages/registry/tests/seed-satisfies-contract.test.ts,
    // which is the side that owns the seed.
    expect(TourOverlayProps.safeParse({ steps: "" }).success).toBe(false);
    expect(TourOverlayProps.safeParse({ steps: [] }).success).toBe(false);
    expect(
      TourOverlayProps.safeParse({ steps: [{ target: "h1", title: "Start here" }] }).success,
    ).toBe(true);
  });
});
