/**
 * AgentBuilderPanel — what a failed Save / Apply looks like.
 *
 * Save used to be called straight from a click handler, so a server error
 * (a project whose folder was missing answered FileNotFoundError) escaped as an
 * uncaught "Runtime ApiError" overlay with nowhere to go. The outcome belongs in
 * the status bar, in words, and Apply must not go on to call the server after a
 * save that did not happen.
 *
 * jsdom + manual createRoot + act() — same house style as ToolPicker.mcp.test.tsx.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class {
    m22 = 1;
    constructor(_: unknown) {}
  };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).PointerEvent) {
  (window as any).PointerEvent = class extends Event {} as any;
}
if (typeof Element !== "undefined" && !(Element.prototype as any).hasPointerCapture) {
  (Element.prototype as any).hasPointerCapture = () => false;
  (Element.prototype as any).releasePointerCapture = () => {};
  (Element.prototype as any).setPointerCapture = () => {};
  (Element.prototype as any).scrollIntoView = () => {};
}

const apiGet = vi.fn(async (_url: string) => []);
const apiPost = vi.fn(async (_url: string, _body?: unknown): Promise<unknown> => ({ saved: true }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (url: string) => apiGet(url),
    post: (url: string, body?: unknown) => apiPost(url, body),
    put: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

import { AgentBuilderPanel } from "../AgentBuilderPanel";
import { useAgentBuilderStore } from "@/stores/agent-builder";

let container: HTMLDivElement;
let root: Root;
let fetchSpy: ReturnType<typeof vi.fn>;
const unhandled: unknown[] = [];
const onUnhandled = (e: unknown) => unhandled.push(e);

beforeEach(() => {
  apiGet.mockClear();
  apiPost.mockReset();
  apiPost.mockResolvedValue({ saved: true });
  useAgentBuilderStore.getState().setCurrentAgent(null);
  fetchSpy = vi.fn();
  (globalThis as any).fetch = fetchSpy;
  unhandled.length = 0;
  process.on("unhandledRejection", onUnhandled);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  process.off("unhandledRejection", onUnhandled);
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function mountEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <div style={{ width: 1000, height: 700 }}>
          <AgentBuilderPanel projectId="p1" />
        </div>
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
  // The list view's "New Agent" opens a blank agent in the editor.
  const newAgent = [...container.querySelectorAll("button")].find((b) => /New Agent/.test(b.textContent ?? ""))!;
  await act(async () => {
    newAgent.click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

const button = (label: RegExp) =>
  [...container.querySelectorAll("button")].find((b) => label.test(b.textContent ?? ""))!;

async function click(el: Element) {
  await act(async () => {
    (el as HTMLButtonElement).click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

/** The agent's own saves: the platform's answer for the save URL, and the calls made to it. */
const SAVE_URL = "/api/projects/p1/agent-definitions";
const saves = () => apiPost.mock.calls.filter((c) => String(c[0]).split("?")[0] === SAVE_URL);
const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
/** Long enough for the builder's own save-after-a-pause (1.2 seconds) to have happened. */
const AUTOSAVE_WAIT = 1500;
const nameBox = () => container.querySelector('input[placeholder="Agent name"]') as HTMLInputElement;
const rename = (value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(nameBox(), value);
    nameBox().dispatchEvent(new Event("input", { bubbles: true }));
  });
const saveState = () => container.querySelector('[data-testid="save-state"]')?.textContent ?? "";

describe("AgentBuilderPanel — a failed save is reported, not thrown", () => {
  it("a save that fails by itself shows the server's words in the status bar, and can be tried again", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) throw new Error("FileNotFoundError: the project folder is missing");
      return { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);

    const bar = container.querySelector('[role="status"]');
    expect(bar?.textContent).toBe("Error: FileNotFoundError: the project folder is missing");
    expect(bar?.className).toMatch(/red/);
    expect(saveState()).toBe("Not saved. Try again");
    expect(saves(), "it does not keep hammering a server that said no").toHaveLength(1);
    expect(unhandled).toEqual([]);

    // the server is back: pressing the status tries again, the message goes away and the toolbar says so
    apiPost.mockImplementation(async () => ({ saved: true }));
    await click(container.querySelector('[data-testid="save-state"]')!);
    expect(saves()).toHaveLength(2);
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(saveState()).toBe("Saved");
  });

  it("Apply stops at a failed save and never calls the server's apply", async () => {
    apiPost.mockRejectedValueOnce(new Error("could not save"));
    await mountEditor();
    await click(button(/Apply/));

    expect(container.querySelector('[role="status"]')?.textContent).toBe("Error: could not save");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
  });

  it("a good save is quiet: no message in the status bar, just Saved in the toolbar", async () => {
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    expect(saves()).toHaveLength(1);
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(saveState()).toBe("Saved");
  });

  it("the server's final message stays visible after Apply finishes", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: error\ndata: {"message":"This project has no generated app yet. Your agent is saved and will be installed when the app is built."}\n\n';
    fetchSpy.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => {
          let sent = false;
          return {
            read: async () =>
              sent ? { done: true, value: undefined } : ((sent = true), { done: false, value: encoder.encode(sse) }),
          };
        },
      },
    });
    await mountEditor();
    await click(button(/Apply/));

    // Apply has finished (the spinner is gone) and the message is still there to read.
    expect(container.querySelector('[role="status"]')?.textContent).toContain("no generated app yet");
    expect(button(/Apply/).hasAttribute("disabled")).toBe(false);
  });

  it("opening the list again clears the last message", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) throw new Error("boom");
      return { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    apiPost.mockImplementation(async () => ({ saved: true }));

    // back to the list, then into a new agent
    const back = container.querySelector("button svg.lucide-arrow-left")?.closest("button") as HTMLButtonElement;
    await click(back);
    await click(button(/New Agent/));
    expect(container.querySelector('[role="status"]')).toBeNull();
  });
});


// ── no Save button: the agent saves itself ───────────────────────────────

describe("AgentBuilderPanel — the agent saves itself", () => {
  it("has no Save button any more", async () => {
    await mountEditor();
    expect(button(/^\s*Save\s*$/)).toBeUndefined();
    expect(container.textContent).toContain("Saves as you edit");
  });

  it("does not save an agent nobody has touched: opening a new agent and leaving leaves nothing behind", async () => {
    await mountEditor();
    await wait(AUTOSAVE_WAIT);
    expect(saves()).toHaveLength(0);
    expect(saveState()).toBe("Saves as you edit");
  });

  it("saves a change a moment after it, with what was typed, and says Saved", async () => {
    await mountEditor();
    await rename("Refund helper");
    expect(saveState(), "between the change and the save").toBe("Unsaved changes");
    expect(saves()).toHaveLength(0);
    await wait(AUTOSAVE_WAIT);
    expect(saves()).toHaveLength(1);
    expect((saves()[0][1] as any).name).toBe("Refund helper");
    expect(saveState()).toBe("Saved");
    await wait(AUTOSAVE_WAIT);
    expect(saves(), "nothing changed since: nothing saved again").toHaveLength(1);
  });

  it("saves once for a burst of typing, not once per key", async () => {
    await mountEditor();
    await rename("R");
    await wait(300);
    await rename("Re");
    await wait(300);
    await rename("Refund");
    await wait(AUTOSAVE_WAIT);
    expect(saves()).toHaveLength(1);
    expect((saves()[0][1] as any).name).toBe("Refund");
  });

  it("saves a change made just before going back to the list, instead of losing it", async () => {
    await mountEditor();
    await rename("Quick change");
    const back = container.querySelector("button svg.lucide-arrow-left")?.closest("button") as HTMLButtonElement;
    await click(back);
    expect(saves()).toHaveLength(1);
    expect((saves()[0][1] as any).name).toBe("Quick change");
  });

  it("Apply still saves first, so what is installed is what is on screen", async () => {
    await mountEditor();
    await rename("Applied name");
    fetchSpy.mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) } });
    await click(button(/Apply/));
    expect(saves().length).toBeGreaterThanOrEqual(1);
    expect((saves()[0][1] as any).name).toBe("Applied name");
  });
});

// ── the Diagram button and the components ────────────────────────────────

describe("AgentBuilderPanel — the diagram page and its components", () => {
  const palette = () => container.textContent?.includes("Agent Nodes") ?? false;
  const diagram = () => button(/^\s*Diagram\s*$/);

  it("has a Diagram button where Save used to be, in front of Test, Find problems and Watch live", async () => {
    await mountEditor();
    const labels = [...container.querySelectorAll("button")].map((b) => (b.textContent ?? "").trim());
    const at = (re: RegExp) => labels.findIndex((l) => re.test(l));
    expect(at(/^Diagram$/)).toBeGreaterThan(-1);
    expect(at(/^Diagram$/)).toBeLessThan(at(/^Test$/));
    expect(at(/^Test$/)).toBeLessThan(at(/Find problems/));
    expect(at(/Find problems/)).toBeLessThan(at(/Watch live/));
  });

  it("shows the components only on the diagram page", async () => {
    await mountEditor();
    expect(palette(), "on the diagram page").toBe(true);
    expect(diagram().getAttribute("aria-pressed")).toBe("true");

    await click(button(/^\s*Test\s*$/));
    expect(palette(), "on the Test page").toBe(false);
    expect(diagram().getAttribute("aria-pressed")).toBe("false");

    await click(diagram());
    expect(palette()).toBe(true);

    await click(button(/Find problems/));
    expect(palette(), "on the Find problems page").toBe(false);
    expect(container.querySelector('[data-testid="agent-blast"]')).not.toBeNull();

    await click(diagram());
    expect(palette()).toBe(true);
    expect(container.querySelector('[data-testid="agent-blast"]'), "the page is gone: the drawing is back").toBeNull();

    await click(button(/Watch live/));
    expect(palette(), "on the Watch live page").toBe(false);
    await click(diagram());
    expect(palette()).toBe(true);
  });

  it("takes the person back to the drawing from wherever they are, with one press", async () => {
    await mountEditor();
    await click(button(/Find problems/));
    await click(button(/^\s*Test\s*$/));
    await click(diagram());
    expect(diagram().getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector('[data-testid="agent-blast"]')).toBeNull();
    expect(palette()).toBe(true);
  });
});


// ── the drawing is verified before it is saved ───────────────────────────

/** What the platform answers when it verified the drawing and refused: HTTP 422 with the problems. */
const refusal = (kind: "problems" | "corrupt", problems: Array<{ code: string; message: string }>) =>
  Object.assign(new Error(`Not saved: ${problems.length} problem${problems.length === 1 ? "" : "s"} to fix first. ${problems[0].message}`), {
    status: 422,
    body: { detail: { msg: "…", kind, problems: problems.map((p) => ({ severity: "error", nodeId: null, ...p })) } },
  });
const NO_PROMPT = { code: "no_prompt_box", message: "The agent has no System Prompt box, so it has no instructions to follow." };
const OTHER = { code: "unknown_table", message: "Tool 'list_x' reads 'x', and this app has no such table." };
const savesWith = (query: string) => saves().filter((c) => String(c[0]).endsWith(query));

describe("AgentBuilderPanel — verified before it is saved", () => {
  it("says what is wrong when the drawing was refused, instead of calling it a failed save, and offers to save it anyway", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) throw refusal("problems", [NO_PROMPT, OTHER]);
      return { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    expect(saveState()).toContain("Not saved: 2 problems to fix");
    expect(container.querySelector('[data-testid="save-state"]')?.getAttribute("title")).toContain("no System Prompt box");
    expect(container.querySelector('[role="status"]'), "a refusal is not an error message").toBeNull();
    expect(container.querySelector('[data-testid="save-anyway"]')).not.toBeNull();
    expect(saves(), "it asked once and does not keep asking").toHaveLength(1);
  });

  it("Save anyway sends the drawing on purpose, and then says Saved", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url === SAVE_URL) throw refusal("problems", [NO_PROMPT]);
      return url.startsWith(SAVE_URL) ? { saved: true } : { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    expect(saveState()).toContain("Not saved: 1 problem to fix");
    await click(container.querySelector('[data-testid="save-anyway"]')!);
    expect(savesWith("?force=true")).toHaveLength(1);
    expect(saveState()).toBe("Saved");
  });

  it("a corrupt drawing cannot be saved on purpose: there is no Save anyway", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) throw refusal("corrupt", [{ code: "dangling_arrow", message: "An arrow points to a box that is not in the drawing." }]);
      return { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    expect(saveState()).toContain("Not saved: 1 problem to fix");
    expect(container.querySelector('[data-testid="save-anyway"]')).toBeNull();
  });

  it("is verified again with the next change, and saved once it is right", async () => {
    let right = false;
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) {
        if (!right) throw refusal("problems", [NO_PROMPT]);
        return { saved: true };
      }
      return { findings: [] };
    });
    await mountEditor();
    await rename("First try");
    await wait(AUTOSAVE_WAIT);
    expect(saveState()).toContain("Not saved");
    right = true; // the person fixed the drawing
    await rename("Second try");
    await wait(AUTOSAVE_WAIT);
    expect(saves()).toHaveLength(2);
    expect(saveState()).toBe("Saved");
  });

  it("Apply saves on purpose, because it asks its own question about the same problems", async () => {
    await mountEditor();
    fetchSpy.mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) } });
    await click(button(/Apply/));
    expect(savesWith("?force=true").length).toBeGreaterThanOrEqual(1);
  });

  it("going back with changes that were refused asks first, and stays when the person says no", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url.split("?")[0] === SAVE_URL) throw refusal("problems", [NO_PROMPT]);
      return { findings: [] };
    });
    await mountEditor();
    await rename("A better name");
    await wait(AUTOSAVE_WAIT);
    const back = () => container.querySelector("button svg.lucide-arrow-left")?.closest("button") as HTMLButtonElement;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await click(back());
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toContain("have problems");
    expect(container.querySelector('input[placeholder="Agent name"]'), "still in the editor").not.toBeNull();
    confirm.mockReturnValue(true);
    await click(back());
    expect(container.querySelector('input[placeholder="Agent name"]'), "left, as the person said").toBeNull();
    expect(saves(), "the refused drawing was not sent again behind their back").toHaveLength(1);
  });
});
