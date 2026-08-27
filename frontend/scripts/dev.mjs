#!/usr/bin/env node
/**
 * `next dev` with a heap large enough to compile the editor tree.
 *
 * ENV-1: on the default heap the Next SSR worker pool dies compiling the
 * editor, so `/editor/[projectId]` and `/org/[orgId]/projects/[projectId]`
 * return HTTP 500 with:
 *
 *     Error: Jest worker encountered 2 child process exceptions, exceeding
 *     retry limit
 *
 * `/` is unaffected, which is what makes it so misleading — it reads as an
 * auth or routing fault rather than an out-of-memory one.
 *
 * Setting NODE_OPTIONS here rather than documenting it means every developer
 * (and every CI job that runs `npm run dev`) gets the working heap without
 * having to know. An existing NODE_OPTIONS is preserved, and an explicit
 * --max-old-space-size wins so this can still be overridden.
 */
import { spawn } from "node:child_process";

const HEAP_FLAG = "--max-old-space-size=8192";
const existing = process.env.NODE_OPTIONS ?? "";

const env = {
  ...process.env,
  NODE_OPTIONS: existing.includes("--max-old-space-size")
    ? existing
    : `${existing} ${HEAP_FLAG}`.trim(),
};

const child = spawn(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["next", "dev", ...process.argv.slice(2)],
  { stdio: "inherit", env, shell: process.platform === "win32" },
);

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 0);
});
