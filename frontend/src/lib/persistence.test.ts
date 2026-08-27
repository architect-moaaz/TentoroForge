import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { buildPersister } from "./persistence";
import { flushPersister, attachPersister } from "./editor-store";
import type { Artifacts } from "@forge/patches";

// Shared spies — tests that need to assert on them access via the mock
const markCleanSpy = vi.fn();
const setSaveErrorSpy = vi.fn();

// Mock the editor-store module so markClean/setSaveError don't error in jsdom
vi.mock("./editor-store", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./editor-store")>();
  return {
    ...actual,
    useEditorStore: {
      getState: () => ({ markClean: markCleanSpy, setSaveError: setSaveErrorSpy }),
      subscribe: vi.fn(() => () => {}),
    },
  };
});

function makeArtifacts(): Artifacts {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2" as const,
        id: "home",
        route: "/",
        root: { id: "n1", type: "Stack", children: [] },
      },
    },
    navFlow: {
      version: "1.0" as const,
      initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [],
      guards: {},
    },
    tokens: {
      color: {}, typography: {}, spacing: {}, radius: {},
      shadow: {}, motion: {}, breakpoints: {},
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  markCleanSpy.mockClear();
  setSaveErrorSpy.mockClear();
  // Stub fetch to resolve successfully
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("buildPersister", () => {
  it("resolves flush() only after the pending debounced save completes", async () => {
    const persister = buildPersister("proj-1", 500);
    const artifacts = makeArtifacts();

    // Trigger a debounced save
    persister.save(artifacts);

    // flush() should cancel the timer and run the writes immediately
    const flushPromise = persister.flush();

    // Let microtasks (fetch promises) settle
    await flushPromise;

    // 1 page schema + nav-flow.json + tokens.json = 3 POSTs
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("isPending() returns true between save() and flush() resolution", async () => {
    const persister = buildPersister("proj-2", 500);
    const artifacts = makeArtifacts();

    persister.save(artifacts);

    // Timer is set — should be pending
    expect(persister.isPending()).toBe(true);

    const flushPromise = persister.flush();

    // After flush resolves, nothing is pending
    await flushPromise;
    expect(persister.isPending()).toBe(false);
  });

  it("save() after flush() still debounces correctly", async () => {
    const persister = buildPersister("proj-3", 500);
    const artifacts = makeArtifacts();

    // First flush cycle
    persister.save(artifacts);
    await persister.flush();

    const callsAfterFirst = (fetch as ReturnType<typeof vi.fn>).mock.calls.length;

    // Second save — advance timers to trigger debounce
    persister.save(artifacts);
    expect(persister.isPending()).toBe(true);
    await vi.runAllTimersAsync();
    expect(persister.isPending()).toBe(false);

    // Should have made another round of 3 POSTs
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterFirst + 3);
  });

  // ── New tests for code-review fixes ──────────────────────────────────────

  it("CRITICAL: a non-2xx response (ok:false) rejects and never markClean()s (no silent data loss)", async () => {
    // A 401/429/500 that returns a Response with ok:false — previously this
    // was console.warn'd and resolved, so runSave reached markClean() and the
    // editor falsely showed "Saved".
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    vi.stubGlobal("fetch", fetchMock);
    const persister = buildPersister("proj-500", 500);
    persister.save(makeArtifacts());
    await expect(persister.flush()).rejects.toThrow(/HTTP 500/);
    expect(markCleanSpy).not.toHaveBeenCalled();
  });

  it("a failed BACKGROUND (debounce) save surfaces a saveError and does not markClean", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal("fetch", fetchMock);
    const persister = buildPersister("proj-403", 500);
    persister.save(makeArtifacts());
    await vi.runAllTimersAsync(); // fire the debounce timer → background save fails
    expect(markCleanSpy).not.toHaveBeenCalled();
    expect(setSaveErrorSpy).toHaveBeenCalledWith(expect.stringContaining("unsaved"));
  });

  it("saveFile rejection propagates through flush()", async () => {
    const fetchMock = vi.fn();
    // First call succeeds (home page schema), second call rejects
    fetchMock
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error("network failure"));
    vi.stubGlobal("fetch", fetchMock);

    const persister = buildPersister("proj-err", 500);
    persister.save(makeArtifacts());

    await expect(persister.flush()).rejects.toThrow("network failure");
    // markClean must NOT have been called when save partially failed
    expect(markCleanSpy).not.toHaveBeenCalled();
  });

  it("concurrent flush() calls both resolve after the same save", async () => {
    const persister = buildPersister("proj-concurrent", 500);
    persister.save(makeArtifacts());

    // Fire two flush() calls without awaiting between them
    const p1 = persister.flush();
    const p2 = persister.flush();

    await Promise.all([p1, p2]);

    // One page + nav-flow + tokens = 3 POSTs, NOT 6
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(3);
  });

  it("save() during in-flight save serialises the second write", async () => {
    // Use controlled fetch promises so we can observe ordering
    let resolveFirst!: () => void;
    const firstDone = new Promise<void>((res) => { resolveFirst = res; });

    const fetchMock = vi.fn().mockImplementation(() => {
      // First three calls (the inflight save) block until we release them
      if (fetchMock.mock.calls.length <= 3) {
        return firstDone.then(() => ({ ok: true }));
      }
      return Promise.resolve({ ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    const persister = buildPersister("proj-serial", 500);
    const arts = makeArtifacts();

    // Start first debounced save
    persister.save(arts);
    await vi.runAllTimersAsync(); // fires timer → inflight starts

    // While first save is still in-flight, schedule another save
    persister.save(arts);

    // Release the first save and advance timers for the second
    resolveFirst();
    await vi.runAllTimersAsync();

    // Verify fetch calls are monotonically ordered — no interleaving
    const orders = fetchMock.mock.invocationCallOrder;
    for (let i = 1; i < orders.length; i++) {
      expect(orders[i]).toBeGreaterThan(orders[i - 1]);
    }
    // Total: 3 (first save) + 3 (second save) = 6
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("flushPersister() resolves immediately after detach", async () => {
    // Re-wire subscribe to return a real unsubscribe fn
    const { useEditorStore } = await import("./editor-store");
    const subscribeMock = useEditorStore.subscribe as ReturnType<typeof vi.fn>;
    let capturedUnsub!: () => void;
    subscribeMock.mockImplementationOnce((_cb: unknown) => {
      capturedUnsub = () => {};
      return capturedUnsub;
    });

    const unsubscribe = attachPersister("proj-detach");
    unsubscribe(); // detach

    // flushPersister should resolve without touching fetch
    await flushPersister();
    expect(fetch).not.toHaveBeenCalled();
  });
});
