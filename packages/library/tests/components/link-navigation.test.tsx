import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { Link } from "../../src/components/Link/Link";
import { NavLink } from "../../src/components/NavLink/NavLink";
import { SkipLink, resolveLandmark } from "../../src/components/SkipLink/SkipLink";
import { pathMatchesRoute, normalisePath } from "../../src/util/routeMatch";

function withNav(ui: React.ReactElement) {
  const nav = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() };
  return { nav, ...render(<NavigatorProvider value={nav}>{ui}</NavigatorProvider>) };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("routeMatch (shared by Redirect and NavLink)", () => {
  it("normalises query, hash and trailing slash away", () => {
    expect(normalisePath("/items/?q=1#x")).toBe("/items");
    expect(normalisePath("/")).toBe("/");
    expect(normalisePath("")).toBe("/");
  });
  it("matches under a preview base path but not on a partial segment", () => {
    expect(pathMatchesRoute("/items", "/p/proj/items")).toBe(true);
    expect(pathMatchesRoute("/items", "/p/proj/line-items")).toBe(false);
    expect(pathMatchesRoute("/", "/p/proj/items")).toBe(false);
    expect(pathMatchesRoute(undefined, "/items")).toBe(false);
  });
});

describe("Link", () => {
  it("with no destination is not a link at all", () => {
    const { container } = withNav(<Link label="Learn more" navigate="" />);
    const a = container.querySelector("a")!;
    // `href=""` used to make this focusable, blue, underlined and inert — an
    // anchor without href is not a link to assistive tech, which is honest.
    expect(a.hasAttribute("href")).toBe(false);
    expect(a).toHaveAttribute("data-link-unset");
    expect(a).toHaveAttribute("aria-disabled", "true");
  });

  it("routes an internal destination through the Navigator", async () => {
    const { nav } = withNav(<Link label="Learn more" navigate="/items" />);
    await userEvent.click(screen.getByText("Learn more"));
    expect(nav.push).toHaveBeenCalledWith("/items");
  });

  it("leaves an external destination to the browser", async () => {
    const { nav, container } = withNav(<Link label="Docs" navigate="https://example.com" />);
    expect(container.querySelector("a")).toHaveAttribute("href", "https://example.com");
    await userEvent.click(screen.getByText("Docs"));
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("target=_blank opens in a new tab with a safe rel, and is not soft-navigated", async () => {
    const { nav, container } = withNav(<Link label="New tab" navigate="/items" target="_blank" />);
    const a = container.querySelector("a")!;
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
    await userEvent.click(a);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("a workflow-only link stays interactive", async () => {
    const dispatch = vi.fn();
    withNav(<Link label="Sign out" navigate="" workflow="auth.signOut" __dispatch={dispatch} />);
    await userEvent.click(screen.getByText("Sign out"));
    expect(dispatch).toHaveBeenCalledWith("auth.signOut", undefined);
  });
});

describe("NavLink", () => {
  it("reads the registry's `target` prop as the destination", () => {
    const { container } = render(<NavLink label="Items" target="/items" />);
    expect(container.querySelector("a")).toHaveAttribute("href", "/items");
  });

  it("with no destination is not a link", () => {
    const { container } = render(<NavLink label="Link" />);
    const a = container.querySelector("a")!;
    expect(a.hasAttribute("href")).toBe(false);
    expect(a).toHaveAttribute("data-navlink-unset");
  });

  it("marks itself current from the browser path when no host supplies one", async () => {
    window.history.replaceState({}, "", "/p/proj/items");
    const { container } = render(<NavLink label="Items" target="/items" />);
    await screen.findByText("Items");
    await vi.waitFor(() =>
      expect(container.querySelector("a")).toHaveAttribute("aria-current", "page"),
    );
  });

  it("does not mark a different route as current", async () => {
    window.history.replaceState({}, "", "/p/proj/orders");
    const { container } = render(<NavLink label="Items" target="/items" />);
    await screen.findByText("Items");
    expect(container.querySelector("a")).not.toHaveAttribute("aria-current");
  });

  it("an explicit currentPath still wins", () => {
    const { container } = render(<NavLink label="Items" target="/items" currentPath="/items" />);
    expect(container.querySelector("a")).toHaveAttribute("aria-current", "page");
  });

  it("renders the declared icon", () => {
    const { container } = render(<NavLink label="Items" target="/items" icon="Home" />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});

describe("SkipLink", () => {
  it("falls back to the <main> landmark when nothing carries the id", async () => {
    document.body.innerHTML = '<main data-project-id="x">content</main>';
    const main = document.querySelector("main")!;
    expect(document.getElementById("main")).toBeNull();
    const el = resolveLandmark("main");
    expect(el).toBe(main);
    // Stamped, so the anchor's own href="#main" resolves natively from now on.
    expect(main.id).toBe("main");
    document.body.innerHTML = "";
  });

  it("never retargets a non-landmark id", () => {
    document.body.innerHTML = "<main>content</main>";
    expect(resolveLandmark("some-other-anchor")).toBeNull();
    document.body.innerHTML = "";
  });

  it("moves focus to the landmark on activation", async () => {
    render(
      <>
        <SkipLink />
        <main data-project-id="x">content</main>
      </>,
    );
    await userEvent.click(screen.getByText("Skip to main content"));
    const main = document.querySelector("main")!;
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(document.activeElement).toBe(main);
  });
});
