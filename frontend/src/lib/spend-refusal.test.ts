/**
 * A refusal at the door (402) is shown in the administrator's own words,
 * with who can change it; any other failure keeps its own message.
 */
import { describe, expect, it } from "vitest";
import { describeRefusal, REFUSAL_HINT } from "@/lib/spend-refusal";

describe("describing a refusal at the door", () => {
  it("repeats a 402's reasons verbatim and says who can lift them", () => {
    const text = describeRefusal(402, "Not started: the organisation Acme holds $3.00 and this is expected to cost about $12.00.", "fallback");
    expect(text.startsWith("Not started: the organisation Acme holds $3.00")).toBe(true);
    expect(text.endsWith(REFUSAL_HINT)).toBe(true);
  });

  it("keeps another status's own detail, without the hint", () => {
    expect(describeRefusal(403, "Organisation is blocked", "fallback")).toBe("Organisation is blocked");
  });

  it("falls back when there is no detail at all", () => {
    expect(describeRefusal(500, null, "The engine refused the run (HTTP 500).")).toBe("The engine refused the run (HTTP 500).");
    expect(describeRefusal(402, undefined, "fallback")).toBe("fallback");
  });
});
