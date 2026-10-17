/**
 * The phone-app step of a build is named for people, not by its node id:
 * "Native Mobile" in the run panel, and counted with the app's screens.
 */
import { describe, expect, it } from "vitest";
import { STAGE_MAKES, labelFor, verbFor } from "@/components/smith/stages";
import { AREAS } from "@/components/smith/questModel";

describe("the native step", () => {
  it("is called Native Mobile, never native_code", () => {
    expect(labelFor("native_code")).toBe("Native Mobile");
    expect(verbFor("native_code")).toBe("Writing each page for the phone in React Native");
    expect(STAGE_MAKES.native_code).toContain("React Native");
  });

  it("counts toward the screens", () => {
    expect(AREAS.find((a) => a.key === "screens")?.steps).toContain("native_code");
  });
});
