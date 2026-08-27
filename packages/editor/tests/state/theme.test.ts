import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";

let store: ReturnType<typeof createEditorStore>;
beforeEach(() => { store = createEditorStore(); });

const tokens = { colors: { "primary.500": "#3b82f6" }, spacing: { "spacing.4": "1rem" } } as any;

describe("theme store slice", () => {
  it("loadTheme sets theme + source + clean", () => {
    store.getState().loadTheme(tokens, "default");
    expect(store.getState().theme).toEqual(tokens);
    expect(store.getState().themeSource).toBe("default");
    expect(store.getState().themeDirty).toBe(false);
  });

  it("setTokenValue updates a token + marks dirty", () => {
    store.getState().loadTheme(tokens, "default");
    store.getState().setTokenValue("colors", "primary.500", "#ff0000");
    expect(store.getState().theme!.colors["primary.500"]).toBe("#ff0000");
    expect(store.getState().themeDirty).toBe(true);
  });

  it("setTokenValue is no-op when theme not loaded", () => {
    store.getState().setTokenValue("colors", "primary.500", "#ff0000");
    expect(store.getState().theme).toBeNull();
  });

  it("markThemeSaved clears dirty", () => {
    store.getState().loadTheme(tokens, "default");
    store.getState().setTokenValue("colors", "primary.500", "#ff0000");
    store.getState().markThemeSaved();
    expect(store.getState().themeDirty).toBe(false);
  });
});
