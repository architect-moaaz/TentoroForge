import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useShortcuts } from "../../src/keyboard/useShortcuts";
import { createEditorStore } from "../../src/state/store";

const page = (): any => ({ schemaVersion: "1", id: "p", route: "/", root: { id: "r", type: "Stack", children: [
  { id: "a", type: "Text", props: { content: "A" } },
]}});

function Probe({ store, onSave }: any) { useShortcuts(store, onSave); return null; }

describe("clipboard shortcuts", () => {
  it("Cmd+C copies selection", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("a");
    render(<Probe store={store} onSave={() => {}} />);
    await userEvent.keyboard("{Meta>}c{/Meta}");
    expect(store.getState().clipboard?.nodes[0].id).toBe("a");
  });

  it("Cmd+V pastes", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("a");
    store.getState().copyToClipboard();
    render(<Probe store={store} onSave={() => {}} />);
    await userEvent.keyboard("{Meta>}v{/Meta}");
    expect(store.getState().pages.p.schema.root.children.length).toBe(2);
  });

  it("Cmd+X cuts", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("a");
    render(<Probe store={store} onSave={() => {}} />);
    await userEvent.keyboard("{Meta>}x{/Meta}");
    expect(store.getState().pages.p.schema.root.children.length).toBe(0);
    expect(store.getState().clipboard?.mode).toBe("cut");
  });
});
