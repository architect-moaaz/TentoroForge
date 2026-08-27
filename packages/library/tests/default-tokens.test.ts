import { describe, it, expect } from "vitest";
import { defaultTokens } from "../src/theme/default-tokens";

function leafPaths(obj: any, prefix = "tokens"): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = `${prefix}.${k}`;
    if (v && typeof v === "object") out.push(...leafPaths(v, path));
    else out.push(path);
  }
  return out.sort();
}

describe("defaultTokens canonical structure", () => {
  it("exposes the contract paths the LLM emits + validator expects", () => {
    const paths = leafPaths(defaultTokens);
    expect(paths).toMatchSnapshot();
  });

  it("has 11-stop ramps for primary/secondary/accent", () => {
    for (const scale of ["primary", "secondary", "accent"] as const) {
      const ramp = (defaultTokens.color as any)[scale];
      expect(Object.keys(ramp).sort((a, b) => +a - +b))
        .toEqual(["50","100","200","300","400","500","600","700","800","900","950"]);
    }
  });

  it("has 3-stop ramps for status colors", () => {
    for (const status of ["success", "warning", "error", "info"] as const) {
      const ramp = (defaultTokens.color as any)[status];
      expect(Object.keys(ramp).sort()).toEqual(["50", "500", "700"]);
    }
  });

  it("has 13-stop spacing scale", () => {
    const stops = Object.keys(defaultTokens.spacing)
      .filter((k) => /^\d+$/.test(k))
      .sort((a, b) => +a - +b);
    expect(stops).toEqual(["0","1","2","3","4","6","8","12","16","24","32","48","64"]);
  });

  it("has typography scale h1..caption", () => {
    expect(Object.keys(defaultTokens.typography.scale).sort())
      .toEqual(["body", "caption", "h1", "h2", "h3"]);
  });
});
