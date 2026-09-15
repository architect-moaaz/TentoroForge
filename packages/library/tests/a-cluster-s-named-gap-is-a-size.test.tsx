import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Cluster } from "../src/components/Cluster/Cluster";

describe("a Cluster's named gap is a size", () => {
  // Every composed page writes `gap: "sm"`; Cluster turned it into
  // `var(--token-sm)`, which nothing defines, so the dashboard's action
  // buttons rendered touching each other.
  it.each([["xs", "0.25rem"], ["sm", "0.5rem"], ["md", "1rem"], ["lg", "1.5rem"], ["tokens.spacing.3", "0.75rem"]])(
    "maps %s to %s", (gap, rem) => {
      const { container } = render(<Cluster gap={gap} justify="end"><button>A</button><button>B</button></Cluster>);
      expect((container.firstChild as HTMLElement).style.gap).toBe(rem);
    },
  );
  it("still resolves a token reference to its variable", () => {
    const { container } = render(<Cluster gap="tokens.space.inline"><span /></Cluster>);
    expect((container.firstChild as HTMLElement).style.gap).toBe("var(--token-space-inline)");
  });
  it("falls back to the density gap when nothing is named", () => {
    const { container } = render(<Cluster><span /></Cluster>);
    expect((container.firstChild as HTMLElement).style.gap).not.toBe("");
  });
});
