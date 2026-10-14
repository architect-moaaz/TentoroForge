import { describe, expect, it } from "vitest";
import { feelToCondition, conditionFields } from "@/lib/feel-to-condition";
import { conditionToFeel } from "@/lib/condition-to-feel";

// What the build, Smith and the tab write — read back into the builder and
// compiled again, it must say the same thing.
const ROUND_TRIP = [
  'status = "done"',
  "amount > 1000",
  "amount >= 10.5",
  'title != ""',
  "dueDate = null",
  "dueDate != null",
  '(status = "doing" and amount > 5000)',
  '(status = "todo" or status = "doing")',
  'status in ["todo", "doing"]',
  'not(status in ["done"])',
  'contains(title, "urgent")',
  'starts_with(code, "INV")',
  '(amount > 5000 and (status = "submitted" or status = "pending"))',
  "approved = true",
  "ownerId = user.id",
];

describe("feelToCondition", () => {
  it.each(ROUND_TRIP)("round-trips %s", (feel) => {
    const tree = feelToCondition(feel);
    expect(tree).toBeTruthy();
    expect(conditionToFeel(tree)).toBe(feel);
  });

  it("reads the forms the build writes that the builder writes differently", () => {
    expect(conditionToFeel(feelToCondition('status = null or status = ""'))).toBe('(status = null or status = "")');
    expect(conditionToFeel(feelToCondition("a > 1 and b < 2 and c = 3"))).toBe("(a > 1 and b < 2 and c = 3)");
    expect(conditionToFeel(feelToCondition("not(a = 1)"))).toBe("not(a = 1)");
  });

  it("treats an empty or always-true condition as no condition", () => {
    expect(feelToCondition("")).toBeNull();
    expect(feelToCondition("true")).toBeNull();
    expect(feelToCondition(undefined)).toBeNull();
  });

  it("answers undefined for what the builder cannot show", () => {
    for (const feel of ["amount * 2 > 10", "count(items) > 3", "status = \"a", "if a then b else c", "a > 1 xor b"]) {
      expect(feelToCondition(feel)).toBeUndefined();
    }
  });

  it("names the fields a condition reads, previous values included", () => {
    expect(conditionFields(feelToCondition('previous.status = "done" and status = "todo"'))).toEqual(
      ["previous.status", "status"]);
  });
});
