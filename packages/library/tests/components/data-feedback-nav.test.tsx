import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Table } from "../../src/components/Table/Table";
import { TableSortable } from "../../src/components/Table/TableSortable";
import { TableProps } from "../../src/components/Table/Table.schema";
import { Alert } from "../../src/components/Alert/Alert";
import { AlertProps } from "../../src/components/Alert/Alert.schema";
import { ConfirmDialog } from "../../src/components/ConfirmDialog/ConfirmDialog";
import { ConfirmDialogProps } from "../../src/components/ConfirmDialog/ConfirmDialog.schema";
import { NavLink } from "../../src/components/NavLink/NavLink";
import { NavLinkProps } from "../../src/components/NavLink/NavLink.schema";
import { Breadcrumb } from "../../src/components/Breadcrumb/Breadcrumb";
import { BreadcrumbProps } from "../../src/components/Breadcrumb/Breadcrumb.schema";
import { ToastProvider, useToast } from "../../src/components/Toast/Toast";

// ----- Table ---------------------------------------------------------------

describe("Table", () => {
  const columns = [
    { key: "name", label: "Name" },
    { key: "age", label: "Age" },
  ];

  it("renders thead with column headers", () => {
    const { container } = render(<Table columns={columns} />);
    const thead = container.querySelector("thead");
    expect(thead).not.toBeNull();
    expect(thead?.textContent).toContain("Name");
    expect(thead?.textContent).toContain("Age");
  });

  it("renders tbody element", () => {
    const { container } = render(<Table columns={columns} />);
    expect(container.querySelector("tbody")).not.toBeNull();
  });

  it("renders a table element", () => {
    const { container } = render(<Table columns={columns} />);
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("validates columns via TableProps zod schema", () => {
    expect(() => TableProps.parse({ columns: [] })).not.toThrow(); // empty columns OK
    expect(() => TableProps.parse({})).toThrow(); // columns required
    expect(() => TableProps.parse({ columns: [{ key: "x", label: "X" }] })).not.toThrow();
  });
});

// ----- TableSortable -------------------------------------------------------

describe("TableSortable", () => {
  const columns = [
    { key: "name", label: "Name" },
    { key: "score", label: "Score" },
  ];

  it("renders thead with sortable column headers", () => {
    const { container } = render(<TableSortable columns={columns} />);
    const thead = container.querySelector("thead");
    expect(thead).not.toBeNull();
    expect(thead?.textContent).toContain("Name");
  });

  it("clicking column header updates sort state (aria-sort)", async () => {
    const { container } = render(<TableSortable columns={columns} />);
    const nameHeader = screen.getByRole("columnheader", { name: /name/i });
    expect(nameHeader).toBeInTheDocument();
    await userEvent.click(nameHeader);
    // After click, column should have sort direction indicator
    expect(nameHeader).toHaveAttribute("aria-sort");
  });
});

// ----- Alert ---------------------------------------------------------------

describe("Alert", () => {
  it("renders message text", () => {
    render(<Alert message="Something went wrong" />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("has role='alert'", () => {
    render(<Alert message="Danger!" variant="danger" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("applies variant neutral by default", () => {
    const { container } = render(<Alert message="Info" />);
    expect(container.querySelector("[role='alert']")).not.toBeNull();
  });

  it("accepts all valid variants", () => {
    const variants = ["neutral", "info", "success", "danger", "warning"] as const;
    for (const variant of variants) {
      const { unmount } = render(<Alert message="Test" variant={variant} />);
      expect(screen.getByRole("alert")).toBeInTheDocument();
      unmount();
    }
  });

  it("validates props via AlertProps zod schema", () => {
    expect(() => AlertProps.parse({ message: "ok" })).not.toThrow();
    expect(() => AlertProps.parse({})).toThrow(); // message required
    expect(() => AlertProps.parse({ message: "ok", variant: "critical" })).toThrow(); // unknown variant
  });
});

// ----- ConfirmDialog -------------------------------------------------------

describe("ConfirmDialog", () => {
  it("is initially closed (content hidden)", () => {
    render(
      <ConfirmDialog
        triggerLabel="Delete"
        title="Confirm Delete"
        description="Are you sure?"
        workflow="deleteItem"
      />
    );
    // Trigger button visible
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    // Dialog content should not be in DOM
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens dialog on trigger click", async () => {
    render(
      <ConfirmDialog
        triggerLabel="Delete"
        title="Confirm Delete"
        description="Are you sure?"
        workflow="deleteItem"
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Confirm Delete")).toBeInTheDocument();
    expect(screen.getByText("Are you sure?")).toBeInTheDocument();
  });

  it("fires workflow on confirm", async () => {
    const dispatch = vi.fn();
    render(
      <ConfirmDialog
        triggerLabel="Delete"
        title="Confirm Delete"
        description="Are you sure?"
        workflow="deleteItem"
        args={{ id: 42 }}
        __dispatch={dispatch}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    // Click the confirm button inside the dialog
    const confirmBtn = screen.getByRole("button", { name: /confirm|yes|ok|delete/i });
    await userEvent.click(confirmBtn);
    expect(dispatch).toHaveBeenCalledWith("deleteItem", { id: 42 });
  });

  it("validates props via ConfirmDialogProps zod schema", () => {
    expect(() =>
      ConfirmDialogProps.parse({
        triggerLabel: "Delete",
        title: "Confirm",
        description: "Sure?",
        workflow: "deleteItem",
      })
    ).not.toThrow();
    expect(() => ConfirmDialogProps.parse({})).toThrow(); // all required
  });
});

// ----- NavLink -------------------------------------------------------------

describe("NavLink", () => {
  it("renders an anchor with the given href", () => {
    render(<NavLink href="/dashboard" currentPath="/dashboard">Dashboard</NavLink>);
    const link = screen.getByRole("link", { name: "Dashboard" });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/dashboard");
  });

  it("sets aria-current='page' when currentPath matches href", () => {
    render(<NavLink href="/dashboard" currentPath="/dashboard">Dashboard</NavLink>);
    expect(screen.getByRole("link")).toHaveAttribute("aria-current", "page");
  });

  it("does not set aria-current when paths differ", () => {
    render(<NavLink href="/settings" currentPath="/dashboard">Settings</NavLink>);
    const link = screen.getByRole("link");
    expect(link).not.toHaveAttribute("aria-current");
  });

  it("renders children correctly", () => {
    render(<NavLink href="/home" currentPath="/other">Home</NavLink>);
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("validates props via NavLinkProps zod schema", () => {
    // hand-authored shape
    expect(() => NavLinkProps.parse({ href: "/home", children: "Home" })).not.toThrow();
    // schema/Figma shape (unifyLabelHref → label + navigate, plus className)
    expect(() => NavLinkProps.parse({ label: "Dashboard", navigate: "/dashboard", className: "px-3" })).not.toThrow();
  });
});

// ----- Breadcrumb ----------------------------------------------------------

describe("Breadcrumb", () => {
  const items = [
    { label: "Home", href: "/" },
    { label: "Products", href: "/products" },
    { label: "Widget" },
  ];

  it("renders all item labels", () => {
    render(<Breadcrumb items={items} />);
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Products")).toBeInTheDocument();
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });

  it("renders separators between items", () => {
    const { container } = render(<Breadcrumb items={items} separator="/" />);
    const seps = container.querySelectorAll("[aria-hidden='true']");
    // 3 items → 2 separators
    expect(seps.length).toBe(2);
  });

  it("renders hrefs for linked items", () => {
    render(<Breadcrumb items={items} />);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute("href", "/products");
  });

  it("renders last item without a link (current page)", () => {
    render(<Breadcrumb items={items} />);
    // Widget has no href → rendered as span/text, not link
    expect(screen.queryByRole("link", { name: "Widget" })).toBeNull();
  });

  it("validates props via BreadcrumbProps zod schema", () => {
    expect(() => BreadcrumbProps.parse({ items: [{ label: "Home" }] })).not.toThrow();
    expect(() => BreadcrumbProps.parse({})).toThrow(); // items required
  });
});

// ----- Toast sanity --------------------------------------------------------

describe("Toast (sanity)", () => {
  it("exports ToastProvider without throwing", () => {
    expect(typeof ToastProvider).toBe("function");
  });

  it("exports useToast hook without throwing", () => {
    expect(typeof useToast).toBe("function");
  });

  it("renders ToastProvider without throwing", () => {
    expect(() => render(<ToastProvider><div>content</div></ToastProvider>)).not.toThrow();
  });
});
