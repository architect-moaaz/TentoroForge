import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DesignTimeProvider } from "@tentoroforge/renderer";
import { FocusTrap } from "../../src/components/FocusTrap/FocusTrap";
import { AutoFocus } from "../../src/components/AutoFocus/AutoFocus";
import { TourOverlay } from "../../src/components/TourOverlay/TourOverlay";
import { TableSortable } from "../../src/components/Table/TableSortable";

/**
 * ONE FILE FOR ONE RULE: a runtime behaviour does not arm around the person
 * building it.
 *
 * Four components were found taking the editor's keyboard, focus or state, and
 * each was reported as its own bug. They are one rule, spelled once as
 * `useRuntimeArmed`. Every case is asserted in BOTH directions, because "off in
 * the editor" is only half of it — turning the behaviour off is trivial and
 * shipping an app whose FocusTrap does not trap is a worse bug than the one
 * being fixed.
 */

const inEditor = (ui: React.ReactElement) => <DesignTimeProvider>{ui}</DesignTimeProvider>;

beforeEach(() => {
  document.body.innerHTML = "";
  try { window.localStorage.clear(); } catch { /* ignore */ }
});

describe("FocusTrap", () => {
  it("traps in a running app", () => {
    render(<FocusTrap><button>inside</button></FocusTrap>);
    const root = document.querySelector('[data-forge-focus-trap="active"]');
    expect(root).not.toBeNull();
    expect(document.activeElement).toBe(screen.getByText("inside"));
  });

  it("does not take focus, or Tab, on an authoring surface", () => {
    // Measured on the canvas: `document.activeElement` was the trap's own root
    // (`tabindex="-1"`) before the author touched anything, and a Tab keydown
    // came back `defaultPrevented === true` — the editor's Tab key was dead for
    // as long as a FocusTrap sat on the page.
    render(inEditor(<FocusTrap><button>inside</button></FocusTrap>));
    expect(document.activeElement).toBe(document.body);
    const root = document.querySelector('[data-forge-focus-trap]')!;
    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    root.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });

  it("still reports what the AUTHOR set, so the panel does not lie", () => {
    render(inEditor(<FocusTrap active><button>inside</button></FocusTrap>));
    const root = document.querySelector("[data-forge-focus-trap]")!;
    expect(root.getAttribute("data-forge-focus-trap")).toBe("inactive");
    expect(root.getAttribute("data-forge-focus-trap-authored")).toBe("active");
  });
});

describe("AutoFocus", () => {
  it("focuses in a running app", () => {
    render(<AutoFocus delayed={false}><button>target</button></AutoFocus>);
    expect(document.activeElement).toBe(screen.getByText("target"));
  });

  it("does not move the caret into the artefact being edited", () => {
    render(inEditor(<AutoFocus delayed={false}><button>target</button></AutoFocus>));
    expect(document.activeElement).toBe(document.body);
  });

  it("a delayed focus can actually be cancelled", async () => {
    // The cleanup was `if (id !== null) clearTimeout(id)` and `id` is null on
    // the queueMicrotask path — i.e. on every modern browser — so an AutoFocus
    // that unmounted in the same tick still stole focus.
    const { unmount } = render(<AutoFocus delayed><button>target</button></AutoFocus>);
    unmount();
    await Promise.resolve();
    expect(document.activeElement).toBe(document.body);
  });
});

describe("TourOverlay", () => {
  const STEPS = [{ target: "body", title: "Step one", body: "hello", placement: "bottom" as const }];

  it("auto-starts in a running app", () => {
    render(<TourOverlay steps={STEPS} storageKey="k1" />);
    expect(screen.getByText("Step one")).toBeInTheDocument();
  });

  it("does not auto-start on an authoring surface, so a stray Escape cannot dismiss it forever", () => {
    // Its Escape handler is `window`-scoped: an Escape pressed anywhere in the
    // editor, for anything at all, ended the tour AND wrote "done" to
    // localStorage — after which it never rendered again on that machine, with
    // no editor control able to clear the flag.
    render(inEditor(<TourOverlay steps={STEPS} storageKey="k2" />));
    expect(screen.queryByText("Step one")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(window.localStorage.getItem("k2")).toBeNull();
  });
});

describe("TableSortable", () => {
  const COLS = [{ key: "name", label: "Name" }, { key: "status", label: "Status" }];

  it("sorts in a running app", () => {
    const onSort = vi.fn();
    render(<TableSortable columns={COLS} onSort={onSort} />);
    fireEvent.click(screen.getByText("Name"));
    expect(onSort).toHaveBeenCalledWith("name", "asc");
    expect(screen.getByText("Name").closest("th")).toHaveAttribute("aria-sort", "ascending");
  });

  it("a header click on the canvas does not mutate the component instead of selecting it", () => {
    const onSort = vi.fn();
    render(inEditor(<TableSortable columns={COLS} onSort={onSort} />));
    const th = screen.getByText("Name").closest("th")!;
    fireEvent.click(th);
    expect(onSort).not.toHaveBeenCalled();
    expect(th).not.toHaveAttribute("aria-sort");
    // The affordance follows the behaviour.
    expect((th as HTMLElement).style.cursor).toBe("default");
  });

  it("accepts the className it declares", () => {
    const { container } = render(<TableSortable columns={COLS} className="my-grid" />);
    expect(container.querySelector("table")!.className).toContain("my-grid");
  });
});
