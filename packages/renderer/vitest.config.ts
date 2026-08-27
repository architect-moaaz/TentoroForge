import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  resolve: {
    alias: {
      // Resolve workspace packages to their TypeScript source in test mode
      // (no build step required for tests).
      "@tentoroforge/schema": resolve(__dirname, "../schema/src/index.ts"),
    },
  },
  test: { include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"] },
});
