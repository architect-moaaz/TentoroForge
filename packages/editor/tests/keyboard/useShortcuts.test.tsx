import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useShortcuts } from "../../src/keyboard/useShortcuts";
import { createEditorStore } from "../../src/state/store";
import { buildSetProp } from "../../src/state/mutations";

function Probe({ store, onSave }: any) {
  useShortcuts(store, onSave);
  return null;
}

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Text", props: { content: "x" } },
});

const PATH = "x";

describe("keyboard shortcuts", () => {
  it("Cmd+Z undoes the last mutation", async () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages[PATH].schema));
    render(<Probe store={store} onSave={() => {}} />);
    const user = userEvent.setup();
    await user.keyboard("{Meta>}z{/Meta}");
    expect((store.getState().pages[PATH].schema.root as any).props.content).toBe("x");
  });

  it("Cmd+Shift+Z redoes", async () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages[PATH].schema));
    store.getState().undo();
    render(<Probe store={store} onSave={() => {}} />);
    const user = userEvent.setup();
    await user.keyboard("{Meta>}{Shift>}z{/Shift}{/Meta}");
    expect((store.getState().pages[PATH].schema.root as any).props.content).toBe("y");
  });

  it("Cmd+S calls onSave", async () => {
    const onSave = vi.fn();
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    render(<Probe store={store} onSave={onSave} />);
    const user = userEvent.setup();
    await user.keyboard("{Meta>}s{/Meta}");
    expect(onSave).toHaveBeenCalled();
  });
});
