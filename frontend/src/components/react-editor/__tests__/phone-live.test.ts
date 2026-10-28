import { describe, expect, it } from "vitest";

import { pictureSource, type LiveStatus } from "../../phone/PhonePreview";

const status = (live?: LiveStatus["state"]) => ({
  state: "ready" as const, servePath: "/api/projects/abc/phone/serve",
  ...(live ? { live: { state: live, path: "/api/projects/abc/phone/live" } } : {}),
});

describe("where the phone picture comes from", () => {
  it("is the live preview, in the Editor, once it is running", () => {
    expect(pictureSource(status("ready"), true)).toBe("live");
  });
  it("is the built picture while the live preview is still starting, so there is always something to look at", () => {
    expect(pictureSource(status("starting"), true)).toBe("built");
    expect(pictureSource(status("off"), true)).toBe("built");
  });
  it("is the built picture when the live preview cannot run or has stopped", () => {
    expect(pictureSource(status("failed"), true)).toBe("built");
  });
  it("is the built picture where nobody asked for the live one (the Phone tab on its own)", () => {
    expect(pictureSource(status("ready"), false)).toBe("built");
  });
  it("is the built picture before the status is known, or from a server that does not have the live preview", () => {
    expect(pictureSource(undefined, true)).toBe("built");
    expect(pictureSource(status(), true)).toBe("built");
  });
});
