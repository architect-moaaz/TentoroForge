import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Page } from "../src";

const EXEMPLARS = [
  "wide-form-accordion",
  "wide-form-tabs",
  "detail-tabs",
  "related-fields-card",
  "narrow-form-flat",
  "dashboard-kpi-grid",
  "dashboard-domain-overview",
  "auth-split-illustration",
];

describe("progressive-disclosure exemplars parse against Page", () => {
  for (const name of EXEMPLARS) {
    it(`${name}.json`, () => {
      const path = resolve(
        __dirname,
        "..",
        "..",
        "..",
        "backend",
        "fixtures",
        "exemplars",
        `${name}.json`,
      );
      const data = JSON.parse(readFileSync(path, "utf8"));
      const r = Page.safeParse(data);
      if (!r.success) {
        const issues = r.error.issues
          .slice(0, 3)
          .map((i) => `${i.path.join(".")}: ${i.message}`);
        throw new Error(`${name} failed: ${issues.join("; ")}`);
      }
      expect(r.success).toBe(true);
    });
  }
});
