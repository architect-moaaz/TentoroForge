import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Heading } from "../../src/components/Heading/Heading";
import { HeadingProps } from "../../src/components/Heading/Heading.schema";
import { Badge } from "../../src/components/Badge/Badge";
import { BadgeProps } from "../../src/components/Badge/Badge.schema";
import { Divider } from "../../src/components/Divider/Divider";
import { DividerProps } from "../../src/components/Divider/Divider.schema";
import { Card } from "../../src/components/Card/Card";
import { CardProps } from "../../src/components/Card/Card.schema";
import { EmptyState } from "../../src/components/EmptyState/EmptyState";
import { EmptyStateProps } from "../../src/components/EmptyState/EmptyState.schema";
import { LoadingState } from "../../src/components/LoadingState/LoadingState";
import { LoadingStateProps } from "../../src/components/LoadingState/LoadingState.schema";
import { Pagination } from "../../src/components/Pagination/Pagination";
import { PaginationProps } from "../../src/components/Pagination/Pagination.schema";

describe("Heading", () => {
  it("renders the level + content", () => {
    const { container } = render(<Heading level={2} content="Title" id="t" />);
    expect(container.querySelector("h2")?.textContent).toBe("Title");
  });
  it("defaults to h2 when no level supplied", () => {
    const { container } = render(<Heading content="Hi" />);
    expect(container.querySelector("h2")).not.toBeNull();
  });
  it("validates props via HeadingProps zod schema", () => {
    expect(() => HeadingProps.parse({ level: 7, content: "x" })).toThrow();
    expect(() => HeadingProps.parse({ level: 2, content: "x" })).not.toThrow();
  });
});

describe("Badge", () => {
  it("renders content text", () => {
    render(<Badge content="Active" variant="success" />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
  it("defaults to neutral variant", () => {
    render(<Badge content="Tag" />);
    expect(screen.getByText("Tag")).toBeInTheDocument();
  });
  it("validates variant via BadgeProps zod schema", () => {
    expect(() => BadgeProps.parse({ content: "x", variant: "unknown" })).toThrow();
    expect(() => BadgeProps.parse({ content: "x", variant: "primary" })).not.toThrow();
  });
});

describe("Divider", () => {
  it("renders a horizontal divider by default", () => {
    const { container } = render(<Divider />);
    expect(container.firstChild).not.toBeNull();
  });
  it("accepts vertical orientation", () => {
    const { container } = render(<Divider orientation="vertical" />);
    expect(container.firstChild).not.toBeNull();
  });
  it("validates orientation via DividerProps zod schema", () => {
    expect(() => DividerProps.parse({ orientation: "diagonal" })).toThrow();
    expect(() => DividerProps.parse({ orientation: "horizontal" })).not.toThrow();
  });
});

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Hello card</Card>);
    expect(screen.getByText("Hello card")).toBeInTheDocument();
  });
  it("renders optional title and footer", () => {
    render(<Card title="My Card" footer="Footer text">content</Card>);
    expect(screen.getByText("My Card")).toBeInTheDocument();
    expect(screen.getByText("Footer text")).toBeInTheDocument();
  });
  it("validates props via CardProps zod schema", () => {
    expect(() => CardProps.parse({})).not.toThrow();
    expect(() => CardProps.parse({ elevation: "extreme" })).toThrow();
  });
});

describe("EmptyState", () => {
  it("renders message", () => {
    render(<EmptyState message="No items found" />);
    expect(screen.getByText("No items found")).toBeInTheDocument();
  });
  it("renders optional icon and action", () => {
    render(<EmptyState message="Empty" icon="inbox" action={{ label: "Add Item", workflow: "addItem" }} />);
    expect(screen.getByText("Empty")).toBeInTheDocument();
    expect(screen.getByText("Add Item")).toBeInTheDocument();
  });
  it("validates props via EmptyStateProps zod schema", () => {
    expect(() => EmptyStateProps.parse({})).toThrow(); // message required
    expect(() => EmptyStateProps.parse({ message: "ok" })).not.toThrow();
  });
});

describe("LoadingState", () => {
  it("renders label", () => {
    render(<LoadingState label="Loading data…" />);
    expect(screen.getByText("Loading data…")).toBeInTheDocument();
  });
  it("renders a spinner role", () => {
    render(<LoadingState label="Wait" />);
    expect(screen.getByRole("status", { name: "Wait" })).toBeInTheDocument();
  });
  it("validates props via LoadingStateProps zod schema", () => {
    expect(() => LoadingStateProps.parse({})).toThrow(); // label required
    expect(() => LoadingStateProps.parse({ label: "ok" })).not.toThrow();
  });
});

describe("Pagination", () => {
  it("shows current page and total pages", () => {
    render(<Pagination currentPage={2} totalPages={5} />);
    expect(screen.getByText(/2/)).toBeInTheDocument();
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });
  it("validates props via PaginationProps zod schema", () => {
    expect(() => PaginationProps.parse({ currentPage: 0, totalPages: 5 })).toThrow(); // min 1
    expect(() => PaginationProps.parse({ currentPage: 1, totalPages: 5 })).not.toThrow();
  });
});
