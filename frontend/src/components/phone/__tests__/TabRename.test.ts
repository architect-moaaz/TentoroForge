import { describe, expect, it } from "vitest";

import { isTabPart } from "../TabRename";

const BACKSLASH = String.fromCharCode(92);

describe("a tab of the phone's bar is told from the rest of a screen", () => {
  it("is the tab layout's own file, on either kind of slash", () => {
    expect(isTabPart({ file: "app/(tabs)/_layout.tsx" })).toBe(true);
    expect(isTabPart({ file: ["native", "app", "(tabs)", "_layout.tsx"].join(BACKSLASH) })).toBe(true);
  });

  it("is not a screen, the root layout, or nothing", () => {
    expect(isTabPart({ file: "src/screens/PAGE-001.tsx" })).toBe(false);
    expect(isTabPart({ file: "app/_layout.tsx" })).toBe(false);
    expect(isTabPart(null)).toBe(false);
  });
});
