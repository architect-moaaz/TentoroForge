import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@tentoroforge/schema": resolve(__dirname, "../schema/src/index.ts"),
      "@tentoroforge/renderer": resolve(__dirname, "../renderer/src/index.ts"),
      "@tentoroforge/library": resolve(__dirname, "../library/src/index.ts"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
