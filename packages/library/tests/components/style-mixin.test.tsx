/**
 * Integration test: StyleSlot mixin on all 17 retrofitted existing components.
 *
 * Each case passes style={{ padding: "tokens.spacing.4" }} and verifies
 * that the outermost DOM element receives the resolved CSS variable.
 *
 * resolveStyle("tokens.spacing.4") → "var(--token-spacing-4)"
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Button } from "../../src/components/Button/Button";
import { IconButton } from "../../src/components/IconButton/IconButton";
import { Link } from "../../src/components/Link/Link";
import { Form } from "../../src/components/Form/Form";
import { Heading } from "../../src/components/Heading/Heading";
import { Badge } from "../../src/components/Badge/Badge";
import { Divider } from "../../src/components/Divider/Divider";
import { Card } from "../../src/components/Card/Card";
import { EmptyState } from "../../src/components/EmptyState/EmptyState";
import { LoadingState } from "../../src/components/LoadingState/LoadingState";
import { Pagination } from "../../src/components/Pagination/Pagination";
import { Table } from "../../src/components/Table/Table";
import { TableSortable } from "../../src/components/Table/TableSortable";
import { Alert } from "../../src/components/Alert/Alert";
import { ConfirmDialog } from "../../src/components/ConfirmDialog/ConfirmDialog";
import { NavLink } from "../../src/components/NavLink/NavLink";
import { Breadcrumb } from "../../src/components/Breadcrumb/Breadcrumb";

const PADDING_STYLE = { padding: "tokens.spacing.4" } as const;
const RESOLVED_PADDING = "var(--token-spacing-4)";

const COLUMNS = [{ key: "id", label: "ID" }];

describe("StyleSlot mixin — existing components", () => {
  it("Button accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Button label="Click" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("IconButton accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <IconButton icon="✕" aria-label="Close" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Link accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Link label="Home" navigate="/home" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Form accepts and applies StyleSlot.padding on outer form element", () => {
    const { container } = render(
      <Form
        workflow="save"
        fields={[{ kind: "text", name: "name", label: "Name" }]}
        style={PADDING_STYLE}
      />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Heading accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Heading content="Hello" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Badge accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Badge content="New" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Divider accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Divider style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Card accepts and applies StyleSlot.padding on outer div", () => {
    const { container } = render(
      <Card style={PADDING_STYLE}>content</Card>
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("EmptyState accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <EmptyState message="Nothing here" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("LoadingState accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <LoadingState label="Loading…" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Pagination accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Pagination currentPage={1} totalPages={5} style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Table accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Table columns={COLUMNS} style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("TableSortable accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <TableSortable columns={COLUMNS} style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Alert accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <Alert message="Something happened" style={PADDING_STYLE} />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("ConfirmDialog accepts StyleSlot.padding on trigger button", () => {
    const { container } = render(
      <ConfirmDialog
        triggerLabel="Open"
        title="Are you sure?"
        description="This cannot be undone"
        workflow="doAction"
        style={PADDING_STYLE}
      />
    );
    // The outermost rendered DOM is the trigger button
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("NavLink accepts and applies StyleSlot.padding", () => {
    const { container } = render(
      <NavLink href="/about" style={PADDING_STYLE}>About</NavLink>
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });

  it("Breadcrumb accepts and applies StyleSlot.padding on nav", () => {
    const { container } = render(
      <Breadcrumb
        items={[{ label: "Home", href: "/" }, { label: "About" }]}
        style={PADDING_STYLE}
      />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.padding).toBe(RESOLVED_PADDING);
  });
});

describe("StyleSlot mixin — backward compatibility (no style prop)", () => {
  // Spot-check: existing behavior unchanged when style is omitted
  it("Button renders without style prop (no regression)", () => {
    const { container } = render(<Button label="Save" />);
    const el = container.firstChild as HTMLElement;
    // padding should come from token, NOT from resolveStyle (which returns {})
    expect(el).toBeInTheDocument();
    expect(el.style.padding).not.toBe(RESOLVED_PADDING);
  });

  it("Heading renders without style prop (no regression)", () => {
    const { container } = render(<Heading content="Title" />);
    const el = container.firstChild as HTMLElement;
    expect(el.tagName).toBe("H2");
    expect(el.textContent).toBe("Title");
  });
});
