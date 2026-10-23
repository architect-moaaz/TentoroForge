import { describe, expect, it } from "vitest";
import { reloadingAfter, requestFor, startOfFrame } from "../PhonePreview";

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

describe("where a phone frame starts", () => {
  it("keeps the screen the person was on when the frame is made again, instead of the app's first screen", () => {
    const first = startOfFrame({ id: "live-0", route: "/" }, "live-0", "/");
    // the person moves around the app: the same frame keeps the address it was made with (a changing src would reload it at every tap)
    expect(startOfFrame(first, "live-0", "/today")).toBe(first);
    expect(startOfFrame(first, "live-0", "/plants/7")).toBe(first);
    // the frame is made again (a reload, or the live picture and the built one swapping): it opens where the person was
    expect(startOfFrame(first, "live-1", "/today")).toEqual({ id: "live-1", route: "/today" });
    expect(startOfFrame(first, "built-1", "/plants/7")).toEqual({ id: "built-1", route: "/plants/7" });
  });

  it("starts at the first screen when no screen has been reported", () => {
    expect(startOfFrame({ id: "a", route: "/x" }, "b", "")).toEqual({ id: "b", route: "/" });
  });
});

describe("the phone between two pages", () => {
  it("is covered from the moment the page says it is going away until the new page has drawn something", () => {
    expect(reloadingAfter("unloading", false)).toBe(true);
    expect(reloadingAfter("route", true)).toBe(true);          // other messages do not end it
    expect(reloadingAfter("tree", true)).toBe(true);
    expect(reloadingAfter("ready", true)).toBe(true);          // the editor's script on the new page started: the app has drawn nothing yet
    expect(reloadingAfter("painted", true)).toBe(false);
  });

  it("is not covered by anything else", () => {
    expect(reloadingAfter("route", false)).toBe(false);
    expect(reloadingAfter("select", false)).toBe(false);
  });
});
