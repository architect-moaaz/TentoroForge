/**
 * What an organisation may use: a feature the platform has not told us
 * about reads as open (the API is the door), a feature it says is off is
 * locked, and the note names who can open it.
 */
import { describe, expect, it } from "vitest";
import { allowed, lockedNote, type FeatureMap } from "@/lib/features";

const map: FeatureMap = {
  code_export: { key: "code_export", name: "Code export", description: "", group: "ship", default_on: false, source_out: true, enforced: "api", enabled: false, source: "default" },
  drafts_room: { key: "drafts_room", name: "Drafts Room", description: "", group: "build", default_on: false, source_out: false, enforced: "api", enabled: false, source: "default" },
  templates: { key: "templates", name: "Templates", description: "", group: "build", default_on: true, source_out: false, enforced: "api", enabled: true, source: "default" },
};

describe("what the organisation may use", () => {
  it("locks what the platform says is off and opens what it says is on", () => {
    expect(allowed(map, "code_export")).toBe(false);
    expect(allowed(map, "drafts_room")).toBe(false);
    expect(allowed(map, "templates")).toBe(true);
  });
  it("reads as open before the features have loaded, so a slow network never locks a screen", () => {
    expect(allowed(undefined, "code_export")).toBe(true);
    expect(allowed({}, "publish")).toBe(true);
  });
  it("tells the person who can open it", () => {
    expect(lockedNote("Code export")).toBe("Code export is not enabled for your organisation. Ask the platform administrator.");
  });
});
