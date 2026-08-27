import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@tentoroforge/schema": resolve(__dirname, "../schema/src/index.ts"),
      "@tentoroforge/renderer": resolve(__dirname, "../renderer/src/index.ts"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
