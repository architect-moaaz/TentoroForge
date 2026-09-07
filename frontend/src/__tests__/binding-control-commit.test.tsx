/**
 * Regression — docs/editor-audit/panels.md, "Bindings — expression input
 * dispatches per keystroke". The hand-written-expression box was wired straight
 * to onChange, so typing `form.email` wrote nine successive bindings into the
 * schema, pushed nine undo entries (editor-store pushes one per dispatch) and
 * re-armed the 500 ms autosave nine times.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { BindingControl } from "@/components/properties/PropControls/BindingControl";
import { useEditorStore } from "@/lib/editor-store";

vi.mock("next/navigation", () => ({ useParams: () => ({ projectId: "p1" }) }));

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 })) as never);
  useEditorStore.setState({
    artifacts: { pageSchemas: { home: { dataSources: [] } }, navFlow: { pages: [] }, tokens: {} } as never,
    currentPageId: "home",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useEditorStore.setState({ artifacts: null, currentPageId: null });
});

describe("BindingControl — the expression box commits once, on blur", () => {
  const expr = () =>
    screen.getByPlaceholderText(/expression/i) as HTMLInputElement;

  it("writes nothing while typing and exactly once on blur", () => {
    const onChange = vi.fn();
    render(<BindingControl label="content" pageId="home" value="" onChange={onChange} />);
    for (const v of ["f", "fo", "for", "form", "form.", "form.email"]) {
      fireEvent.change(expr(), { target: { value: v } });
    }
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(expr());
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("form.email");
  });

  it("Escape abandons the edit", () => {
    const onChange = vi.fn();
    render(<BindingControl label="content" pageId="home" value="row.id" onChange={onChange} />);
    fireEvent.change(expr(), { target: { value: "garbage" } });
    fireEvent.keyDown(expr(), { key: "Escape" });
    fireEvent.blur(expr());
    expect(onChange).not.toHaveBeenCalled();
    expect(expr().value).toBe("row.id");
  });

  it("a committed value from outside re-syncs the box", () => {
    const { rerender } = render(
      <BindingControl label="content" pageId="home" value="a.b" onChange={() => {}} />,
    );
    expect(expr().value).toBe("a.b");
    rerender(<BindingControl label="content" pageId="home" value="c.d" onChange={() => {}} />);
    expect(expr().value).toBe("c.d");
  });
});
