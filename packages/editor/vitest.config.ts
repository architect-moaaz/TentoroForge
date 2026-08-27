import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@tentoroforge/schema": new URL("../schema/src/index.ts", import.meta.url).pathname,
      "@tentoroforge/renderer": new URL("../renderer/src/index.ts", import.meta.url).pathname,
      "@tentoroforge/library": new URL("../library/src/index.ts", import.meta.url).pathname,
    },
  },
});
