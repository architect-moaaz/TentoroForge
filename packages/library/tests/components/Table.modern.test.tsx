import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { Table } from "../../src/components/Table/Table";
import { TableProps } from "../../src/components/Table/Table.schema";

const cols = [
  { key: "name", label: "Name" },
  { key: "status", label: "Status" },
  { key: "amount", label: "Amount" },
];
const rows = [
  { id: "1", name: "Alpha", status: "active", amount: 100 },
  { id: "2", name: "Beta", status: "pending", amount: 50 },
  { id: "3", name: "Gamma", status: "active", amount: 75 },
];

describe("Table — modern data mode", () => {
  it("renders headers and rows from data", () => {
    render(<Table columns={cols} rows={rows} />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("renders status-like columns as humanized badges", () => {
    render(<Table columns={cols} rows={rows} />);
    // "active" → "Active" badge (appears twice)
    expect(screen.getAllByText("Active").length).toBe(2);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("global search filters rows", () => {
    render(<Table columns={cols} rows={rows} />);
    fireEvent.change(screen.getByPlaceholderText("Search…"), { target: { value: "beta" } });
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("sorts when a header is clicked", () => {
    const { container } = render(<Table columns={cols} rows={rows} pageSize={0} />);
    fireEvent.click(screen.getByText("Amount")); // asc → 50,75,100
    const firstRowCells = container.querySelectorAll("tbody tr")[0].querySelectorAll("td");
    expect(firstRowCells[0].textContent).toContain("Beta"); // amount 50 is smallest
  });

  it("supports row selection with select-all", () => {
    render(<Table columns={cols} rows={rows} selectable />);
    const boxes = screen.getAllByRole("checkbox");
    fireEvent.click(boxes[0]); // header select-all
    expect(screen.getByText("3 selected")).toBeInTheDocument();
  });

  it("paginates when rows exceed pageSize", () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ id: String(i), name: `Row ${i}`, status: "open", amount: i }));
    render(<Table columns={cols} rows={many} pageSize={3} />);
    expect(screen.getByText(/1–3 of 7/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/4–6 of 7/)).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<Table columns={cols} rows={[]} emptyText="No records yet." />);
    expect(screen.getByText("No records yet.")).toBeInTheDocument();
  });

  it("makes rows link when rowHref is given", () => {
    const { container } = render(<Table columns={cols} rows={rows} rowHref="/x/{id}" />);
    const linkRows = container.querySelectorAll('tbody tr[role="link"]');
    expect(linkRows.length).toBe(3);
  });

  it("validates props including new features", () => {
    expect(() => TableProps.parse({ columns: cols, rows: rows, selectable: true, pageSize: 10, title: "T" })).not.toThrow();
    expect(() => TableProps.parse({ columns: null })).not.toThrow(); // null → []
  });
});

describe("Table — legacy children mode", () => {
  it("renders provided rows and headers", () => {
    render(
      <Table columns={cols}>
        <tr><td>Legacy A</td><td>x</td><td>1</td></tr>
      </Table>,
    );
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Legacy A")).toBeInTheDocument();
  });
});
