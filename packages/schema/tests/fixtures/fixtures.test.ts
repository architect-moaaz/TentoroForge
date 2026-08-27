import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { Page } from "../../src";

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadFixture(name: string): unknown {
  const text = readFileSync(resolve(__dirname, name), "utf-8");
  return JSON.parse(text);
}

describe("canonical fixtures parse cleanly", () => {
  it.each([
    ["list", "list-page.json"],
    ["detail", "detail-page.json"],
    ["form", "form-page.json"],
  ])("%s page parses", (_n, file) => {
    const doc = loadFixture(file);
    expect(() => Page.parse(doc)).not.toThrow();
  });
});
