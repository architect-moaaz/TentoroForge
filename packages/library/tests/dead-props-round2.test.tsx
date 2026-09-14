/**
 * Round 2 of the registry-vs-component conformance fixes. Every test here fails
 * against the pre-fix source.
 *
 * Companion to registry-prop-passthrough.test.ts: that one proves the value
 * reaches the component, these prove the component does something with it.
 * Both layers are needed — several of these props were already "fixed" in the
 * component while the zod schema was still dropping them on the way in.
 */
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Select } from "../src/components/Select/Select";
import { Input, parseValidation } from "../src/components/Input/Input";
import { Cascader } from "../src/components/Cascader/Cascader";
import { ActivityFeed } from "../src/components/ActivityFeed/ActivityFeed";
import { DataGrid } from "../src/components/DataGrid/DataGrid";
import { ApprovalStepper } from "../src/components/ApprovalStepper/ApprovalStepper";

const OPTS = [
  { value: "a", label: "Apple" },
  { value: "b", label: "Banana" },
  { value: "c", label: "Cherry" },
];

describe("Select.multiple", () => {
  it("renders a multi-select when set, a single one when not", () => {
    const multi = render(<Select name="f" label="F" options={OPTS} multiple />)
      .container.querySelector("select") as HTMLSelectElement;
    expect(multi.multiple).toBe(true);

    const single = render(<Select name="f" label="F" options={OPTS} />)
      .container.querySelector("select") as HTMLSelectElement;
    expect(single.multiple).toBe(false);
  });

  it("round-trips a comma-joined selection through value/onChange", () => {
    const seen: string[] = [];
    const { container } = render(
      <Select name="f" label="F" options={OPTS} multiple value="a,c" onChange={(v) => seen.push(v)} />,
    );
    const el = container.querySelector("select") as HTMLSelectElement;
    // the incoming "a,c" is split back onto the option elements
    expect(Array.from(el.selectedOptions, (o) => o.value)).toEqual(["a", "c"]);

    // and a new selection comes back out joined the same way
    for (const o of Array.from(el.options)) o.selected = o.value === "b" || o.value === "c";
    fireEvent.change(el);
    expect(seen).toEqual(["b,c"]);
  });

  it("a single select is still handed a string, not an array", () => {
    const seen: string[] = [];
    const { container } = render(
      <Select name="f" label="F" options={OPTS} value="b" onChange={(v) => seen.push(v)} />,
    );
    const el = container.querySelector("select") as HTMLSelectElement;
    expect(el.value).toBe("b");
    fireEvent.change(el, { target: { value: "c" } });
    expect(seen).toEqual(["c"]);
  });
});

describe("Input.validation", () => {
  it("parses the rule expression into the validators shape", () => {
    expect(parseValidation("required")).toEqual({ required: true });
    expect(parseValidation("min:3|max:8")).toEqual({ minLength: 3, maxLength: 8 });
    expect(parseValidation("minLength:2, maxLength:4")).toEqual({ minLength: 2, maxLength: 4 });
    expect(parseValidation("required|pattern:^[A-Z]+$")).toEqual({ required: true, pattern: "^[A-Z]+$" });
  });

  it("lets a pattern contain the rule separator, because it takes the remainder", () => {
    expect(parseValidation("required|pattern:^(a|b)$"))
      .toEqual({ required: true, pattern: "^(a|b)$" });
  });

  it("ignores nonsense rather than throwing or blanking the field", () => {
    expect(parseValidation("wat|min:notanumber|")).toEqual({});
    expect(parseValidation(undefined)).toEqual({});
    expect(parseValidation("")).toEqual({});
    expect(parseValidation(42 as unknown)).toEqual({});
  });

  it("applies the parsed rules to the rendered input", () => {
    const el = render(<Input name="e" label="E" type="text" validation="required|min:3|max:8" />)
      .container.querySelector("input") as HTMLInputElement;
    expect(el.required).toBe(true);
    expect(el.minLength).toBe(3);
    expect(el.maxLength).toBe(8);
  });

  it("gives an email rule a pattern", () => {
    const el = render(<Input name="e" label="E" type="text" validation="email" />)
      .container.querySelector("input") as HTMLInputElement;
    expect(el.getAttribute("pattern")).toContain("@");
    // a real address matches it, a bare word does not
    const re = new RegExp(`^${el.getAttribute("pattern")}$`);
    expect(re.test("a@b.co")).toBe(true);
    expect(re.test("nope")).toBe(false);
  });

  it("the structured validators object wins over the expression", () => {
    const el = render(
      <Input name="e" label="E" type="text" validation="required|min:3" validators={{ min: 9 }} />,
    ).container.querySelector("input") as HTMLInputElement;
    // `validators.min` (9) beats the expression's min:3 even though the two
    // write DIFFERENT keys for the same bound — the merge has to notice that.
    expect(el.minLength).toBe(9);
    // … while `required`, which the object does not mention, still comes from it
    expect(el.required).toBe(true);
  });

  it("renders unchanged when no validation is given", () => {
    const el = render(<Input name="e" label="E" type="text" />)
      .container.querySelector("input") as HTMLInputElement;
    expect(el.required).toBe(false);
    expect(el.getAttribute("pattern")).toBeNull();
  });
});

describe("Cascader.placeholder", () => {
  it("shows the placeholder when there is nothing to cascade through", () => {
    const { container } = render(<Cascader options={[]} placeholder="Pick a region…" />);
    expect(container.querySelector("[data-cascader-placeholder]")?.textContent)
      .toBe("Pick a region…");
  });

  it("does not show it once there are options — the columns are the UI", () => {
    const { container } = render(
      <Cascader options={[{ value: "x", label: "X" }]} placeholder="Pick a region…" />,
    );
    expect(container.querySelector("[data-cascader-placeholder]")).toBeNull();
  });
});

describe("ActivityFeed.showFilter", () => {
  const entries = [
    { id: "1", actorName: "Ada", action: "created", target: "Report", category: "create", timestamp: "2026-01-01T00:00:00Z" },
    { id: "2", actorName: "Bo", action: "approved", target: "Report", category: "approve", timestamp: "2026-01-02T00:00:00Z" },
    { id: "3", actorName: "Cy", action: "updated", target: "Report", category: "update", timestamp: "2026-01-03T00:00:00Z" },
  ];

  it("renders no filter row when the toggle is off", () => {
    const { container } = render(<ActivityFeed entries={entries as never} />);
    expect(container.querySelector("[data-activity-filter]")).toBeNull();
  });

  it("renders one chip per category present, plus All", () => {
    const { container } = render(<ActivityFeed entries={entries as never} showFilter />);
    const chips = Array.from(container.querySelectorAll("[data-activity-filter-chip]"));
    expect(chips.map((c) => c.getAttribute("data-activity-filter-chip")))
      .toEqual(["all", "create", "approve", "update"]);
  });

  it("filters the feed when a chip is clicked, and restores it on All", () => {
    const { container } = render(<ActivityFeed entries={entries as never} showFilter />);
    const rows = () => container.querySelectorAll("ol > li").length;
    expect(rows()).toBe(3);

    fireEvent.click(container.querySelector('[data-activity-filter-chip="approve"]')!);
    expect(rows()).toBe(1);
    expect(container.textContent).toContain("Bo");
    expect(container.textContent).not.toContain("Ada");

    fireEvent.click(container.querySelector('[data-activity-filter-chip="all"]')!);
    expect(rows()).toBe(3);
  });

  it("offers no chips when the entries carry no categories", () => {
    const plain = [{ id: "1", actorName: "Ada", action: "did", target: "x", timestamp: "2026-01-01T00:00:00Z" }];
    const { container } = render(<ActivityFeed entries={plain as never} showFilter />);
    expect(container.querySelector("[data-activity-filter]")).toBeNull();
  });
});

describe("DataGrid.expandable", () => {
  const columns = [{ key: "name", label: "Name" }];
  const rows = [{ id: "r1", name: "Ada", email: "ada@example.com", role: "admin" }];

  it("renders no expand affordance when the toggle is off", () => {
    const { container } = render(<DataGrid columns={columns as never} rows={rows as never} />);
    expect(container.querySelector("[data-row-expand]")).toBeNull();
  });

  it("expands a row into a detail panel and collapses it again", () => {
    const { container } = render(
      <DataGrid columns={columns as never} rows={rows as never} expandable />,
    );
    const toggle = container.querySelector('[data-row-expand="r1"]') as HTMLButtonElement;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("[data-row-detail]")).toBeNull();

    fireEvent.click(toggle);
    const detail = container.querySelector('[data-row-detail="r1"]');
    expect(detail).not.toBeNull();
    // the detail shows the fields the columns do NOT already display
    expect(detail!.textContent).toContain("ada@example.com");
    expect(detail!.textContent).toContain("admin");

    fireEvent.click(container.querySelector('[data-row-expand="r1"]') as HTMLButtonElement);
    expect(container.querySelector("[data-row-detail]")).toBeNull();
  });

  it("spans the detail cell across every column, including its own", () => {
    const { container } = render(
      <DataGrid columns={columns as never} rows={rows as never} expandable selectable />,
    );
    fireEvent.click(container.querySelector('[data-row-expand="r1"]') as HTMLButtonElement);
    const td = container.querySelector("[data-row-detail] td") as HTMLTableCellElement;
    // 1 column + select column + expand column
    expect(td.colSpan).toBe(3);
  });
});

describe("ApprovalStepper.onStepClick", () => {
  const steps = [
    { id: "s1", label: "Submit", status: "approved" as const },
    { id: "s2", label: "Review", status: "current" as const },
  ];

  it("leaves steps inert when no workflow is named", () => {
    const { container } = render(<ApprovalStepper steps={steps} />);
    expect(container.querySelector('li[role="button"]')).toBeNull();
    expect(container.querySelector("[data-forge-workflow]")).toBeNull();
  });

  it("marks every step as an activatable control when a workflow is named", () => {
    const { container } = render(<ApprovalStepper steps={steps} onStepClick="approve-step" />);
    const items = container.querySelectorAll('li[role="button"]');
    expect(items.length).toBe(2);
    expect(items[0].getAttribute("data-forge-workflow")).toBe("approve-step");
    expect((items[0] as HTMLElement).tabIndex).toBe(0);
  });

  it("does the same in the vertical orientation", () => {
    const { container } = render(
      <ApprovalStepper steps={steps} orientation="vertical" onStepClick="approve-step" />,
    );
    expect(container.querySelectorAll('li[role="button"]').length).toBe(2);
  });

  it("an empty workflow id is not a workflow", () => {
    const { container } = render(<ApprovalStepper steps={steps} onStepClick="" />);
    expect(container.querySelector('li[role="button"]')).toBeNull();
  });
});
