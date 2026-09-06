import { describe, it, expect } from "vitest";
import { interpolate } from "../src/runtime/interpolate";

// A drawn session row shows one timestamp as "10:00", "Monday" and "1
// September". Bound to a record, the same three come from one field.
describe("a timestamp formatted three ways", () => {
  const ctx = { item: { startsAt: "2026-09-01T10:00:00.000Z" } } as any;
  it("time, weekday and date formatters read the same field", () => {
    const time = String(interpolate("{{item.startsAt|time:en-GB}}", ctx));
    const day = String(interpolate("{{item.startsAt|weekday:en-GB}}", ctx));
    const date = String(interpolate("{{item.startsAt|date:en-GB}}", ctx));
    expect(time).toMatch(/^\d{2}:\d{2}$/);
    expect(day).toBe("Tuesday");
    expect(date).toBe("1 September");
  });
  it("an Arabic locale writes the day in Arabic", () => {
    expect(String(interpolate("{{item.startsAt|weekday:ar}}", ctx))).toBe("الثلاثاء");
  });
});
