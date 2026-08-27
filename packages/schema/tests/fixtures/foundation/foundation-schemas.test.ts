// Validates the Product slice schemas that live in the app-foundation template.
// These are the same schemas that will be loaded by the schema registry at
// runtime. Running them here confirms they satisfy `Page` before any generated
// app is instantiated.
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { Page } from "../../../src";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Foundation schemas live in the app-foundation template, four directories up.
const SCHEMAS_DIR = resolve(
  __dirname,
  "../../../../../backend/templates/app-foundation/src/schemas/products"
);

function loadFoundationSchema(file: string): unknown {
  const text = readFileSync(resolve(SCHEMAS_DIR, file), "utf-8");
  return JSON.parse(text);
}

describe("foundation Product slice schemas parse cleanly", () => {
  it.each([
    ["list",   "list.json"],
    ["detail", "detail.json"],
    ["form",   "form.json"],
  ])("products/%s schema validates against Page", (_label, file) => {
    const doc = loadFoundationSchema(file);
    expect(() => Page.parse(doc)).not.toThrow();
  });
});
