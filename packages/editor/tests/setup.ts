import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Ensure @testing-library/react cleans up the DOM after each test.
// Vitest does not expose afterEach as a global (without globals:true), so
// @testing-library/react's auto-cleanup never fires — we register it here.
afterEach(() => cleanup());

// jsdom doesn't implement ResizeObserver — provide a no-op polyfill
if (typeof ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom doesn't implement scrollIntoView — dnd-kit KeyboardSensor uses it
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}
