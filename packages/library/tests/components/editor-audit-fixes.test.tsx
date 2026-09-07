/**
 * Regression tests for the editor-audit round-3/4 component fixes.
 *
 * One test per behavioural fix, keyed to the finding it closes:
 *   input C5  — Scanner holds its own value (useFieldValue)
 *   input C7  — document-level listeners are inert on editor chrome
 *   input C8  — five `name` props now render a named form control
 *   input C3  — component-side empty/inert guards
 *   display C5 — explicit Badge.variant beats inference; Avatar xs/xl are real
 *   display C6 — ApprovalStepper keys fall back to the index
 *   display C9 — FeatureCard resolves its icon name
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { Scanner } from "../../src/components/Scanner/Scanner";
import { SegmentedControl } from "../../src/components/SegmentedControl/SegmentedControl";
import { Transfer } from "../../src/components/Transfer/Transfer";
import { RichTextEditor } from "../../src/components/RichTextEditor/RichTextEditor";
import { Calendar } from "../../src/components/Calendar/Calendar";
import { GlobalSearch } from "../../src/components/GlobalSearch/GlobalSearch";
import { KeyboardShortcuts } from "../../src/components/KeyboardShortcuts/KeyboardShortcuts";
import { ThemeToggle } from "../../src/components/ThemeToggle/ThemeToggle";
import { Badge } from "../../src/components/Badge/Badge";
import { Avatar } from "../../src/components/Avatar/Avatar";
import { ApprovalStepper } from "../../src/components/ApprovalStepper/ApprovalStepper";
import { FeatureCard } from "../../src/components/FeatureCard/FeatureCard";
import { Wizard } from "../../src/components/Wizard/Wizard";

const hidden = (container: HTMLElement, name: string) =>
  container.querySelector<HTMLInputElement>(`input[type="hidden"][name="${name}"]`);

// ── input C5 ────────────────────────────────────────────────────────────────
describe("input C5 — Scanner holds its own value", () => {
  it("keeps a scanned code with no parent onChange", () => {
    render(<Scanner label="RFID" />);
    fireEvent.change(screen.getByLabelText(/rfid code/i), { target: { value: "RF-42" } });
    fireEvent.click(screen.getByRole("button", { name: /scan/i }));
    expect(screen.getByText("RF-42")).toBeInTheDocument();
    expect(screen.getByTestId("scan-result").getAttribute("data-status")).toBe("success");
  });

  it("is genuinely controlled when both value and onChange are supplied", () => {
    const onChange = vi.fn();
    render(<Scanner value="SEED" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/rfid code/i), { target: { value: "NEW" } });
    fireEvent.click(screen.getByRole("button", { name: /scan/i }));
    expect(onChange).toHaveBeenCalledWith("NEW");
    // The parent owns the value, so the display stays on the parent's value.
    expect(screen.getByText("SEED")).toBeInTheDocument();
  });
});

// ── input C7 ────────────────────────────────────────────────────────────────
describe("input C7 — global listeners ignore the editor's own chrome", () => {
  let canvas: HTMLElement;
  let chrome: HTMLInputElement;

  beforeEach(() => {
    canvas = document.createElement("div");
    canvas.setAttribute("data-canvas-root", "");
    document.body.appendChild(canvas);
    chrome = document.createElement("input"); // stands in for the palette search box
    document.body.appendChild(chrome);
  });
  afterEach(() => {
    canvas.remove();
    chrome.remove();
    delete document.documentElement.dataset.theme;
  });

  it("GlobalSearch does not steal Ctrl+K aimed at editor chrome", () => {
    render(<GlobalSearch workflow="search" />, { container: canvas });
    const ev = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true, cancelable: true });
    Object.defineProperty(ev, "target", { value: chrome });
    document.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(document.activeElement).not.toBe(screen.getByLabelText("Global search"));
  });

  it("GlobalSearch still answers Cmd+K in a generated app (no canvas root)", () => {
    render(<GlobalSearch workflow="search" />);
    const ev = new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true, cancelable: true });
    document.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });

  it("KeyboardShortcuts ignores '?' typed into editor chrome", () => {
    render(<KeyboardShortcuts shortcuts={[{ keys: "?", label: "Help" }]} />, { container: canvas });
    const ev = new KeyboardEvent("keydown", { key: "?", bubbles: true, cancelable: true });
    Object.defineProperty(ev, "target", { value: document.body });
    act(() => { document.dispatchEvent(ev); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("KeyboardShortcuts still opens on '?' in a generated app", () => {
    render(<KeyboardShortcuts shortcuts={[{ keys: "?", label: "Help" }]} />);
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "?", bubbles: true, cancelable: true }));
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("ThemeToggle themes the canvas root, not the editor's <html>", () => {
    render(<ThemeToggle />, { container: canvas });
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(canvas.dataset.theme).toBe("light");
    const before = window.localStorage.getItem("forge-theme");
    fireEvent.click(screen.getByRole("button"));
    expect(canvas.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(window.localStorage.getItem("forge-theme")).toBe(before);
  });

  it("ThemeToggle still writes documentElement in a generated app", () => {
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

// ── input C8 ────────────────────────────────────────────────────────────────
describe("input C8 — `name` renders a named form control", () => {
  it("SegmentedControl submits its selection", () => {
    const { container } = render(
      <SegmentedControl name="mode" options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} />,
    );
    expect(hidden(container, "mode")?.value).toBe("a");
    fireEvent.click(screen.getByText("B"));
    expect(hidden(container, "mode")?.value).toBe("b");
  });

  it("Transfer submits its selection as JSON", () => {
    const { container } = render(
      <Transfer name="picked" options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} />,
    );
    expect(hidden(container, "picked")?.value).toBe("[]");
    fireEvent.click(screen.getByText("A"));
    fireEvent.click(screen.getByLabelText("move right"));
    expect(hidden(container, "picked")?.value).toBe('["a"]');
  });

  it("RichTextEditor submits its HTML", () => {
    const { container } = render(<RichTextEditor name="body" />);
    const region = screen.getByRole("textbox");
    region.innerHTML = "<p>hi</p>";
    fireEvent.input(region);
    expect(hidden(container, "body")?.value).toBe("<p>hi</p>");
  });

  it("Calendar submits the selected date", () => {
    const { container } = render(<Calendar name="due" value="2026-03-04" />);
    expect(hidden(container, "due")?.value).toBe("2026-03-04");
  });

  it("Scanner submits the scanned code", () => {
    const { container } = render(<Scanner name="tag" />);
    fireEvent.change(screen.getByLabelText(/rfid code/i), { target: { value: "RF-9" } });
    fireEvent.click(screen.getByRole("button", { name: /scan/i }));
    expect(hidden(container, "tag")?.value).toBe("RF-9");
  });

  it("renders no hidden input when `name` is absent", () => {
    const { container } = render(<Scanner />);
    expect(container.querySelector('input[type="hidden"]')).toBeNull();
  });
});

// ── input C3 ────────────────────────────────────────────────────────────────
describe("input C3 — component-side empty/inert guards", () => {
  it("Wizard with no steps does not open on an armed review screen", () => {
    render(<Wizard steps={[]} />);
    expect(screen.queryByRole("button", { name: /^submit$/i })).toBeNull();
  });

  it("GlobalSearch does not dispatch a workflow named ''", () => {
    // `fire()` injects a <button data-forge-workflow> and clicks it; watch for
    // that click rather than for DOM mutations (RTL mounts its own container).
    const seen: string[] = [];
    const listener = (e: Event) => {
      const el = e.target as HTMLElement;
      const wf = el?.getAttribute?.("data-forge-workflow");
      if (wf !== null && wf !== undefined) seen.push(wf);
    };
    document.addEventListener("click", listener, true);
    vi.useFakeTimers();
    try {
      render(<GlobalSearch workflow="" debounceMs={1} />);
      fireEvent.change(screen.getByLabelText("Global search"), { target: { value: "drill" } });
      act(() => { vi.advanceTimersByTime(50); });
      expect(seen).toEqual([]);
    } finally {
      vi.useRealTimers();
      document.removeEventListener("click", listener, true);
    }
  });

  it("GlobalSearch still dispatches a configured workflow", () => {
    const seen: string[] = [];
    const listener = (e: Event) => {
      const wf = (e.target as HTMLElement)?.getAttribute?.("data-forge-workflow");
      if (wf) seen.push(wf);
    };
    document.addEventListener("click", listener, true);
    vi.useFakeTimers();
    try {
      render(<GlobalSearch workflow="search" debounceMs={1} />);
      fireEvent.change(screen.getByLabelText("Global search"), { target: { value: "drill" } });
      act(() => { vi.advanceTimersByTime(50); });
      expect(seen).toEqual(["search"]);
    } finally {
      vi.useRealTimers();
      document.removeEventListener("click", listener, true);
    }
  });
});

// ── display C5 ──────────────────────────────────────────────────────────────
describe("display C5 — explicit props win", () => {
  it("an explicit Badge.variant beats content inference", () => {
    render(<Badge content="Active" variant="danger" />);
    const pill = screen.getByRole("status");
    expect(pill.className).toContain("color-error-100");
    expect(pill.className).not.toContain("color-success-100");
  });

  it("still infers when no variant is given", () => {
    render(<Badge content="Active" />);
    expect(screen.getByRole("status").className).toContain("color-success-100");
  });

  it("Avatar xs and xl are distinct sizes", () => {
    const { container: xs } = render(<Avatar name="Jane Doe" size="xs" />);
    const { container: xl } = render(<Avatar name="Jane Doe" size="xl" />);
    const { container: md } = render(<Avatar name="Jane Doe" size="md" />);
    const cls = (c: HTMLElement) => c.querySelector("span")!.className;
    expect(cls(xs)).not.toContain("h-10 w-10");
    expect(cls(xl)).not.toContain("h-10 w-10");
    expect(cls(md)).toContain("h-10 w-10");
    expect(cls(xs)).not.toBe(cls(xl));
  });
});

// ── display C6 ──────────────────────────────────────────────────────────────
describe("display C6 — ApprovalStepper keys on the index when id is absent", () => {
  it("renders id-less steps without a React key warning", () => {
    const warn = vi.spyOn(console, "error").mockImplementation(() => {});
    const steps = [
      { label: "Submitted", status: "approved" as const },
      { label: "Manager review", status: "current" as const },
      { label: "Finance", status: "pending" as const },
    ];
    const { unmount } = render(<ApprovalStepper steps={steps} />);
    unmount();
    render(<ApprovalStepper steps={steps} orientation="vertical" />);
    const keyWarnings = warn.mock.calls.filter((c) => String(c[0]).includes('unique "key"'));
    expect(keyWarnings).toEqual([]);
    warn.mockRestore();
  });
});

// ── display C9 ──────────────────────────────────────────────────────────────
describe("display C9 — FeatureCard resolves its icon", () => {
  it("renders an svg for a real Lucide name", () => {
    const { container } = render(<FeatureCard title="T" description="D" icon="Sparkles" />);
    expect(container.querySelectorAll("svg").length).toBe(1);
  });

  it("marks an unresolvable icon name instead of rendering an empty square", () => {
    const { container } = render(<FeatureCard title="T" description="D" icon="NotAnIcon" />);
    expect(container.querySelector("[data-unresolved-icon]")).not.toBeNull();
  });

  it("passes a literal glyph straight through", () => {
    render(<FeatureCard title="T" description="D" icon="→" />);
    expect(screen.getByText("→")).toBeInTheDocument();
  });
});
