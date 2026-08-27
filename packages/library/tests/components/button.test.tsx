import { describe, it, expect, vi } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "../../src/components/Button/Button";
import { ButtonProps } from "../../src/components/Button/Button.schema";
import { IconButton } from "../../src/components/IconButton/IconButton";
import { IconButtonProps } from "../../src/components/IconButton/IconButton.schema";
import { Link } from "../../src/components/Link/Link";
import { LinkProps } from "../../src/components/Link/Link.schema";

describe("Button", () => {
  it("renders the label and applies primary variant styles by default", () => {
    render(<Button label="Save" />);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toBeInTheDocument();
  });
  it("dispatches onClick → workflow ref via injected dispatcher", async () => {
    const dispatch = vi.fn();
    render(<Button label="Delete" workflow="deleteProduct" args={{ id: 1 }} __dispatch={dispatch} />);
    await userEvent.click(screen.getByRole("button"));
    expect(dispatch).toHaveBeenCalledWith("deleteProduct", { id: 1 });
  });
  it("supports disabled and loading states", () => {
    const { rerender } = render(<Button label="x" disabled />);
    expect(screen.getByRole("button")).toBeDisabled();
    rerender(<Button label="x" loading />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
  });
  it("disables itself while the workflow dispatch promise is in flight", async () => {
    let resolveDispatch!: () => void;
    const pending = new Promise<void>((r) => {
      resolveDispatch = r;
    });
    const dispatch = vi.fn(() => pending);
    render(<Button label="Submit" workflow="createProduct" __dispatch={dispatch} />);
    const btn = screen.getByRole("button");

    await userEvent.click(btn);
    expect(dispatch).toHaveBeenCalledWith("createProduct", undefined);
    expect(btn).toBeDisabled();

    await act(async () => {
      resolveDispatch();
      await pending;
    });
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("ignores re-clicks while a dispatch is already in flight", async () => {
    const pending = new Promise<void>(() => {});
    const dispatch = vi.fn(() => pending);
    render(<Button label="Submit" workflow="wf" __dispatch={dispatch} />);
    const btn = screen.getByRole("button");
    await userEvent.click(btn);
    await userEvent.click(btn);
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it("does not dispatch when disabled", async () => {
    const dispatch = vi.fn();
    render(<Button label="Save" workflow="save" __dispatch={dispatch} disabled />);
    await userEvent.click(screen.getByRole("button"));
    expect(dispatch).not.toHaveBeenCalled();
  });
  it("validates props via ButtonProps zod schema", () => {
    expect(() => ButtonProps.parse({ label: "ok" })).not.toThrow();
    // label is now optional (no min-length) so MCP-derived schemas with only
    // className render with a default instead of "⚠ invalid props"
    expect(() => ButtonProps.parse({ label: "" })).not.toThrow();
    expect(() => ButtonProps.parse({ label: "ok", variant: "invalid" })).toThrow();
  });
});

describe("IconButton", () => {
  it("renders with aria-label", () => {
    render(<IconButton icon="✕" aria-label="Close" />);
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
  it("dispatches workflow via injected dispatcher", async () => {
    const dispatch = vi.fn();
    render(<IconButton icon="🗑" aria-label="Delete" workflow="deleteItem" __dispatch={dispatch} />);
    await userEvent.click(screen.getByRole("button"));
    expect(dispatch).toHaveBeenCalledWith("deleteItem", undefined);
  });
  it("validates props via IconButtonProps zod schema", () => {
    expect(() => IconButtonProps.parse({ icon: "x", "aria-label": "Close" })).not.toThrow();
    // aria-label is now optional (component supplies a fallback)
    expect(() => IconButtonProps.parse({ icon: "x" })).not.toThrow();
    // accepts the Figma pipeline shape: iconSrc + className, no icon/aria-label
    expect(() => IconButtonProps.parse({ iconSrc: "/api/asset/x.svg", className: "w-9 h-9" })).not.toThrow();
  });
  it("renders an <img> for an iconSrc and falls back to a generic aria-label", () => {
    const { container } = render(<IconButton iconSrc="/api/asset/x.svg" className="w-9 h-9" />);
    expect(screen.getByRole("button", { name: "icon button" })).toBeInTheDocument();
    expect(container.querySelector('img[src="/api/asset/x.svg"]')).not.toBeNull();
  });
});

describe("Link", () => {
  it("renders an anchor with the navigate href", () => {
    render(<Link label="Home" navigate="/home" />);
    const anchor = screen.getByRole("link", { name: "Home" });
    expect(anchor).toBeInTheDocument();
    expect(anchor).toHaveAttribute("href", "/home");
  });
  it("dispatches optional analytics workflow via injected dispatcher when clicked", async () => {
    const dispatch = vi.fn();
    render(<Link label="About" navigate="/about" workflow="trackNav" __dispatch={dispatch} />);
    await userEvent.click(screen.getByRole("link"));
    expect(dispatch).toHaveBeenCalledWith("trackNav", undefined);
  });
  it("validates props via LinkProps zod schema", () => {
    expect(() => LinkProps.parse({ label: "Home", navigate: "/home" })).not.toThrow();
    // label now has a default ("Link") so omitting it no longer throws — MCP
    // schemas sometimes emit only navigate without a label
    expect(() => LinkProps.parse({ navigate: "/home" })).not.toThrow();
  });
});
