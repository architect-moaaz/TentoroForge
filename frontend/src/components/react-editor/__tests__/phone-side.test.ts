import { afterEach, describe, expect, it, vi } from "vitest";

import { PLAN_CHANGED, editorApi } from "../api";
import { surfaceToShow } from "../EditorSurfaces";

describe("which side of the Editor is shown", () => {
  it("is the only side the application has", () => {
    expect(surfaceToShow({ web: true, phone: false }, null)).toBe("web");
    expect(surfaceToShow({ web: false, phone: true }, null)).toBe("phone");
  });

  it("ignores a remembered choice the application can no longer honour", () => {
    expect(surfaceToShow({ web: false, phone: true }, "web")).toBe("phone");
    expect(surfaceToShow({ web: true, phone: false }, "phone")).toBe("web");
  });

  it("is the one asked for when there are both, and the website until one is", () => {
    expect(surfaceToShow({ web: true, phone: true }, "phone")).toBe("phone");
    expect(surfaceToShow({ web: true, phone: true }, "web")).toBe("web");
    expect(surfaceToShow({ web: true, phone: true }, null)).toBe("web");
  });
});

describe("a change to the pages, the menu or the look is announced once it is saved", () => {
  afterEach(() => vi.unstubAllGlobals());

  const answer = (ok: boolean) =>
    vi.stubGlobal("fetch", vi.fn(async () =>
      ok ? new Response(JSON.stringify({ ok: true }), { status: 200 })
         : new Response(JSON.stringify({ detail: { code: "refused", message: "No." } }), { status: 422 })));

  async function heard(run: () => Promise<unknown>) {
    const seen = vi.fn();
    window.addEventListener(PLAN_CHANGED, seen);
    try { await run().catch(() => undefined); } finally { window.removeEventListener(PLAN_CHANGED, seen); }
    return seen.mock.calls.length;
  }

  it("for the look, a page and the menu", async () => {
    answer(true);
    expect(await heard(() => editorApi.setTheme("p", { colors: { primary: "#112233" } }))).toBe(1);
    expect(await heard(() => editorApi.updatePage("p", "PAGE-001", { name: "Home" }))).toBe(1);
    expect(await heard(() => editorApi.setNavigation("p", { initialRoute: "/" }))).toBe(1);
  });

  it("and not when it was refused", async () => {
    answer(false);
    expect(await heard(() => editorApi.setTheme("p", { colors: { primary: "#112233" } }))).toBe(0);
    expect(await heard(() => editorApi.setNavigation("p", { initialRoute: "/" }))).toBe(0);
  });

  it("and reading does not announce anything", async () => {
    answer(true);
    expect(await heard(() => editorApi.theme("p"))).toBe(0);
    expect(await heard(() => editorApi.pages("p"))).toBe(0);
  });
});
