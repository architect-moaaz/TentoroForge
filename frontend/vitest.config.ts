import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
  },
  // Source files rely on Next.js's automatic JSX runtime (no `import React`).
  // Tell esbuild to do the same during vitest transforms — otherwise the
  // classic runtime fires and every source-file JSX call throws
  // `React is not defined`.
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
