import { describe, it, expect } from "vitest";
import { describeDetail } from "@/lib/api";
describe("plain", () => { it("x", () => {
  const d = (msg: string, f: string) => describeDetail([{ msg, loc: ["body", f] }]);
  expect(d("String should have at most 120 characters", "name")).toBe("Name can be at most 120 characters long.");
  expect(d("Value error, give the new app a name", "name")).toBe("Give the new app a name.");
  expect(d("Input should be greater than or equal to 0", "price_cents")).toBe("Price cents must be 0 or more.");
  expect(d("Input should be a valid integer", "rating")).toBe("Rating must be a whole number.");
  expect(d("String should have at least 1 character", "reason")).toBe("Reason can't be empty.");
});});
