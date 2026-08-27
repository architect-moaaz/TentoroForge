import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EditableLineGrid } from "../src/components/EditableLineGrid/EditableLineGrid";

const baseColumns = [
  { key: "name", label: "Item", type: "text" as const, width: "200px" },
  { key: "qty", label: "Qty", type: "number" as const, align: "right" as const },
  { key: "price", label: "Price", type: "currency" as const, align: "right" as const },
];

describe("EditableLineGrid — basic rendering", () => {
  it("renders column headers from the columns prop", () => {
    render(<EditableLineGrid columns={baseColumns} rows={[]} />);
    expect(screen.getByText("Item")).toBeTruthy();
    expect(screen.getByText("Qty")).toBeTruthy();
    expect(screen.getByText("Price")).toBeTruthy();
  });

  it("renders empty state when no rows", () => {
    render(<EditableLineGrid columns={baseColumns} rows={[]} emptyMessage="No items yet." />);
    expect(screen.getByText("No items yet.")).toBeTruthy();
  });

  it("renders a text input for type:text cells", () => {
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "Gloves", qty: 10, price: 1.5 }]}
      />,
    );
    const nameInput = screen.getByDisplayValue("Gloves") as HTMLInputElement;
    expect(nameInput.type).toBe("text");
  });

  it("renders number inputs for type:number and type:currency cells", () => {
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "Gloves", qty: 10, price: 1.5 }]}
      />,
    );
    expect((screen.getByDisplayValue("10") as HTMLInputElement).type).toBe("number");
    expect((screen.getByDisplayValue("1.5") as HTMLInputElement).type).toBe("number");
  });
});

describe("EditableLineGrid — controlled edits", () => {
  it("emits onRowsChange when a text cell is edited", () => {
    const onChange = vi.fn();
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "Gloves", qty: 10, price: 1.5 }]}
        onRowsChange={onChange}
      />,
    );
    const nameInput = screen.getByDisplayValue("Gloves") as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Forceps" } });
    expect(onChange).toHaveBeenCalledWith([
      { id: 1, name: "Forceps", qty: 10, price: 1.5 },
    ]);
  });

  it("emits onRowsChange with a numeric value when a number cell is edited", () => {
    const onChange = vi.fn();
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "Gloves", qty: 10, price: 1.5 }]}
        onRowsChange={onChange}
      />,
    );
    const qtyInput = screen.getByDisplayValue("10") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "25" } });
    expect(onChange).toHaveBeenCalledWith([
      { id: 1, name: "Gloves", qty: 25, price: 1.5 },
    ]);
  });

  it("remove button drops the row when removable=true", () => {
    const onChange = vi.fn();
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[
          { id: 1, name: "Gloves", qty: 10, price: 1.5 },
          { id: 2, name: "Forceps", qty: 5, price: 2.5 },
        ]}
        removable={true}
        onRowsChange={onChange}
      />,
    );
    const removeBtns = screen.getAllByLabelText("Remove row");
    expect(removeBtns).toHaveLength(2);
    fireEvent.click(removeBtns[0]);
    expect(onChange).toHaveBeenCalledWith([
      { id: 2, name: "Forceps", qty: 5, price: 2.5 },
    ]);
  });
});

describe("EditableLineGrid — totals footer", () => {
  it("renders auto-computed subtotal from price*qty", () => {
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[
          { id: 1, name: "Gloves", qty: 10, price: 1.5 },   // 15
          { id: 2, name: "Forceps", qty: 4,  price: 2.5 },  // 10
        ]}
        totals={{ auto: true, taxLabel: "VAT", currency: "AED" }}
      />,
    );
    // 15 + 10 = 25 — formatted "25.00 AED" — appears in BOTH the subtotal
    // and total rows since tax is 0 (no taxRate supplied), so use getAllByText.
    const matches = screen.getAllByText("25.00 AED");
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Subtotal")).toBeTruthy();
    expect(screen.getByText("Total")).toBeTruthy();
  });

  it("applies taxRate to derive tax + total when not supplied", () => {
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "X", qty: 1, price: 100 }]}
        totals={{ auto: true, taxRate: 0.05, taxLabel: "VAT", currency: "AED" }}
      />,
    );
    expect(screen.getByText("100.00 AED")).toBeTruthy(); // subtotal
    expect(screen.getByText("5.00 AED")).toBeTruthy();    // 5% VAT
    expect(screen.getByText("105.00 AED")).toBeTruthy();  // total
  });

  it("explicit subtotal/tax/total override auto values", () => {
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[{ id: 1, name: "X", qty: 99, price: 99 }]}
        totals={{
          auto: true,
          subtotal: 200, tax: 10, total: 210,
          taxLabel: "VAT", currency: "AED",
        }}
      />,
    );
    expect(screen.getByText("200.00 AED")).toBeTruthy();
    expect(screen.getByText("10.00 AED")).toBeTruthy();
    expect(screen.getByText("210.00 AED")).toBeTruthy();
  });

  it("no totals prop → no footer", () => {
    const { container } = render(
      <EditableLineGrid columns={baseColumns} rows={[{ id: 1, name: "X" }]} />,
    );
    expect(container.querySelector("dl")).toBeNull();
  });
});

describe("EditableLineGrid — lookup input", () => {
  it("submits onLookup when Enter is pressed", () => {
    const onLookup = vi.fn();
    render(
      <EditableLineGrid
        columns={baseColumns}
        rows={[]}
        showLookup={true}
        lookupPlaceholder="Add item — enter name, code, or barcode"
        onLookup={onLookup}
      />,
    );
    const lookup = screen.getByPlaceholderText(
      "Add item — enter name, code, or barcode",
    ) as HTMLInputElement;
    fireEvent.change(lookup, { target: { value: "SKU-001" } });
    fireEvent.keyDown(lookup, { key: "Enter" });
    expect(onLookup).toHaveBeenCalledWith("SKU-001");
    // Field clears after submission.
    expect(lookup.value).toBe("");
  });

  it("ignores empty/whitespace-only submissions", () => {
    const onLookup = vi.fn();
    render(
      <EditableLineGrid columns={baseColumns} rows={[]} showLookup onLookup={onLookup} />,
    );
    const lookup = screen.getByPlaceholderText(/add item/i);
    fireEvent.keyDown(lookup, { key: "Enter" });
    expect(onLookup).not.toHaveBeenCalled();
  });
});

describe("EditableLineGrid — readonly columns + select cells", () => {
  it("readonly column renders a span, not an input", () => {
    const cols = [
      { key: "id", label: "ID", type: "readonly" as const },
      { key: "name", label: "Item", type: "text" as const },
    ];
    render(<EditableLineGrid columns={cols} rows={[{ id: "PO-001", name: "X" }]} />);
    // The id "PO-001" must be visible but NOT as an input value.
    expect(screen.getByText("PO-001")).toBeTruthy();
    // X is in a text input
    expect((screen.getByDisplayValue("X") as HTMLInputElement).type).toBe("text");
  });

  it("select column renders an option list", () => {
    const cols = [
      {
        key: "category", label: "Category", type: "select" as const,
        options: [
          { label: "Surgery", value: "surgery" },
          { label: "Pharmacy", value: "pharmacy" },
        ],
      },
    ];
    const onChange = vi.fn();
    render(
      <EditableLineGrid
        columns={cols}
        rows={[{ id: 1, category: "surgery" }]}
        onRowsChange={onChange}
      />,
    );
    const select = screen.getByDisplayValue("Surgery") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "pharmacy" } });
    expect(onChange).toHaveBeenCalledWith([{ id: 1, category: "pharmacy" }]);
  });
});
