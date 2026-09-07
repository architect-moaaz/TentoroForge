/**
 * Phase 6 — the repeating-row editor for option-shaped arrays.
 *
 * `control:"json"` made Select/RadioGroup/MultiSelect option lists editable at
 * all, but the thing being edited is nearly always [{value,label}] and a raw
 * textarea makes adding one option a brace-balancing exercise where a single
 * typo refuses the whole commit. These tests pin the two properties that make
 * the row editor safe to point at a prop whose shape nobody declared:
 *
 *   1. it never rewrites a shape it did not understand — it hands the value back
 *      to the JSON editor untouched;
 *   2. it keeps JsonControl's commit contract (one commit per field, on blur —
 *      editor-store pushes one undo entry per dispatch).
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { RowsControl, JsonControl } from "@/components/properties/PropControls";
import { analyzeRows } from "@/components/properties/PropControls/RowsControl";

afterEach(cleanup);

describe("shape sniffing", () => {
  it("reads the three value-key spellings and the label", () => {
    expect(analyzeRows([{ value: "a", label: "A" }]))
      .toMatchObject({ kind: "objects", valueKey: "value", labelKey: "label" });
    expect(analyzeRows([{ key: "a", label: "A" }]))
      .toMatchObject({ kind: "objects", valueKey: "key" });
    expect(analyzeRows([{ id: "a", title: "A" }]))
      .toMatchObject({ kind: "objects", valueKey: "id", labelKey: "title" });
  });

  it("reads a plain string list", () => {
    expect(analyzeRows(["a", "b"])).toEqual({ kind: "strings" });
  });

  it("treats an unset or empty prop as a fresh {value,label} list", () => {
    for (const v of [undefined, null, []]) {
      expect(analyzeRows(v)).toMatchObject({ kind: "objects", valueKey: "value", labelKey: "label" });
    }
  });

  it("stands down for shapes it cannot read", () => {
    // No value/key/id on every row…
    expect(analyzeRows([{ href: "/a", label: "A" }]).kind).toBe("unknown");
    // …rows that are not all the same kind…
    expect(analyzeRows(["a", { value: "b" }]).kind).toBe("unknown");
    // …a value key missing from ONE row (a partially-hand-edited list)…
    expect(analyzeRows([{ value: "a" }, { label: "B" }]).kind).toBe("unknown");
    // …and anything that is not a list at all.
    expect(analyzeRows({ value: "a" }).kind).toBe("unknown");
  });
});

describe("rows the editor understands", () => {
  const opts = [
    { value: "one", label: "Option one" },
    { value: "two", label: "Option two" },
  ];

  it("shows one row per entry", () => {
    render(<RowsControl label="options" value={opts} onChange={() => {}} />);
    expect((screen.getByLabelText("options row 2 value") as HTMLInputElement).value).toBe("two");
  });

  it("commits a field edit once, on blur", () => {
    const onChange = vi.fn();
    render(<RowsControl label="options" value={opts} onChange={onChange} />);
    const cell = screen.getByLabelText("options row 1 label");
    for (const v of ["O", "Op", "Opt"]) fireEvent.change(cell, { target: { value: v } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(cell);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith([
      { value: "one", label: "Opt" },
      { value: "two", label: "Option two" },
    ]);
  });

  it("Escape abandons a field edit", () => {
    const onChange = vi.fn();
    render(<RowsControl label="options" value={opts} onChange={onChange} />);
    const cell = screen.getByLabelText("options row 1 value");
    fireEvent.change(cell, { target: { value: "garbage" } });
    fireEvent.keyDown(cell, { key: "Escape" });
    fireEvent.blur(cell);
    expect(onChange).not.toHaveBeenCalled();
    expect((cell as HTMLInputElement).value).toBe("one");
  });

  it("adds, removes and reorders", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RowsControl label="options" value={opts} onChange={onChange} />);

    fireEvent.click(screen.getByLabelText("Add row to options"));
    expect(onChange).toHaveBeenLastCalledWith([...opts, { value: "", label: "" }]);

    fireEvent.click(screen.getByLabelText("Move options row 2 up"));
    expect(onChange).toHaveBeenLastCalledWith([opts[1], opts[0]]);

    fireEvent.click(screen.getByLabelText("Remove options row 1"));
    expect(onChange).toHaveBeenLastCalledWith([opts[1]]);

    // The ends of the list cannot be pushed off it.
    rerender(<RowsControl label="options" value={opts} onChange={onChange} />);
    expect((screen.getByLabelText("Move options row 1 up") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Move options row 2 down") as HTMLButtonElement).disabled).toBe(true);
  });

  it("preserves keys it does not show", () => {
    const onChange = vi.fn();
    const withExtras = [{ value: "a", label: "A", disabled: true, icon: "star" }];
    render(<RowsControl label="options" value={withExtras} onChange={onChange} />);
    const cell = screen.getByLabelText("options row 1 label");
    fireEvent.change(cell, { target: { value: "Alpha" } });
    fireEvent.blur(cell);
    expect(onChange).toHaveBeenCalledWith([
      { value: "a", label: "Alpha", disabled: true, icon: "star" },
    ]);
    // …and says so, so the user does not think they were dropped.
    expect(screen.getByText(/Also keeps: disabled, icon/)).toBeTruthy();
  });

  it("edits a plain string list as single fields", () => {
    const onChange = vi.fn();
    render(<RowsControl label="tags" value={["a", "b"]} onChange={onChange} />);
    expect(screen.queryByLabelText("tags row 1 label")).toBeNull();
    const cell = screen.getByLabelText("tags row 1 value");
    fireEvent.change(cell, { target: { value: "alpha" } });
    fireEvent.blur(cell);
    expect(onChange).toHaveBeenCalledWith(["alpha", "b"]);
  });
});

describe("shapes it does not understand are handed back, not rewritten", () => {
  it("falls through to the JSON editor with a reason", () => {
    const onChange = vi.fn();
    const odd = [{ href: "/a", label: "A" }];
    render(<RowsControl label="items" value={odd} onChange={onChange} />);
    const box = screen.getByLabelText("items JSON") as HTMLTextAreaElement;
    expect(JSON.parse(box.value)).toEqual(odd);
    expect(screen.getByText(/Editing as JSON/)).toBeTruthy();
    // Merely rendering must not touch the value.
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps parse-or-refuse in the escape hatch", () => {
    const onChange = vi.fn();
    render(<RowsControl label="items" value={[{ href: "/a" }]} onChange={onChange} />);
    const box = screen.getByLabelText("items JSON");
    fireEvent.change(box, { target: { value: '[{"href": ' } });
    fireEvent.blur(box);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("Not saved");
  });

  it("understood rows can still be opened as JSON on demand", () => {
    render(<RowsControl label="options" value={[{ value: "a", label: "A" }]} onChange={() => {}} />);
    fireEvent.click(screen.getByText("Edit as JSON"));
    expect(screen.getByLabelText("options JSON")).toBeTruthy();
    fireEvent.click(screen.getByText("Edit as rows"));
    expect(screen.getByLabelText("options row 1 value")).toBeTruthy();
  });
});

describe("JsonControl delegates on the value's shape", () => {
  it("an array gets the row editor", () => {
    render(<JsonControl label="options" value={[{ value: "a", label: "A" }]} onChange={() => {}} />);
    expect(screen.getByLabelText("options row 1 value")).toBeTruthy();
  });

  it("an object (an AppShell slot) stays raw JSON", () => {
    render(<JsonControl label="sidebar" value={{ type: "SideNav" }} onChange={() => {}} />);
    expect(screen.getByLabelText("sidebar JSON")).toBeTruthy();
    expect(screen.queryByLabelText("sidebar row 1 value")).toBeNull();
  });

  it("an unset slot stays raw JSON — an empty box is how you author an object", () => {
    render(<JsonControl label="sidebar" value={undefined} onChange={() => {}} />);
    expect(screen.getByLabelText("sidebar JSON")).toBeTruthy();
  });
});
