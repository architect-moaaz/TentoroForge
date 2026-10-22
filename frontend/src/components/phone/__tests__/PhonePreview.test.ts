import { describe, expect, it } from "vitest";
import { requestFor } from "../PhonePreview";

describe("what the phone preview hands Smith", () => {
  it("names the screen, the part and where it came from", () => {
    const text = requestFor(
      "/pantry",
      { tagName: "div", textContent: "Add item", source: { file: "src/screens/PAGE-001.tsx", line: 86, component: "Button" } },
      "  make it green ",
    );
    expect(text).toBe('On the phone screen at /pantry, the part that says "Add item" (src/screens/PAGE-001.tsx:86): make it green');
  });

  it("describes a part with no words by what it is", () => {
    const text = requestFor("/", { tagName: "div", textContent: "", source: { file: "app/index.tsx", line: 3, component: "View" } }, "round the corners");
    expect(text).toBe("On the phone app's first screen, a View element (app/index.tsx:3): round the corners");
  });

  it("is about the whole screen when nothing is picked", () => {
    expect(requestFor("/login", null, "add a logo")).toBe("On the phone screen at /login, this screen: add a logo");
  });
});
