// jsdom shims the engine's hooks need (useViewport → matchMedia, ResizeObserver).
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  // @ts-expect-error - assigning a minimal stub
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}
if (typeof globalThis.ResizeObserver === "undefined") {
  // @ts-expect-error - minimal stub
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
