import { describe, it, expect } from "vitest";
import {
  gapClass,
  paddingClasses,
  marginClasses,
  textColorClass,
  bgColorClass,
  radiusClass,
  resolveTypography,
  alignClass,
  justifyClass,
  iconSizeClass,
  avatarSizeClass,
  buildClasses,
  tailwindToSpacing,
  tailwindToRadius,
} from "../src/tokens.js";

describe("Token System", () => {
  describe("gapClass", () => {
    it("should map spacing tokens to Tailwind gap classes", () => {
      expect(gapClass("xs")).toBe("gap-1");
      expect(gapClass("sm")).toBe("gap-2");
      expect(gapClass("md")).toBe("gap-4");
      expect(gapClass("lg")).toBe("gap-6");
      expect(gapClass("xl")).toBe("gap-8");
      expect(gapClass("2xl")).toBe("gap-12");
    });
  });

  describe("paddingClasses", () => {
    it("should handle simple token", () => {
      expect(paddingClasses("md")).toBe("p-4");
      expect(paddingClasses("lg")).toBe("p-6");
    });

    it("should handle x/y shorthand", () => {
      expect(paddingClasses({ x: "md", y: "sm" })).toBe("px-4 py-2");
      expect(paddingClasses({ x: "lg" })).toBe("px-6");
    });

    it("should handle individual sides", () => {
      expect(paddingClasses({ top: "sm", bottom: "lg" })).toBe("pt-2 pb-6");
    });
  });

  describe("marginClasses", () => {
    it("should handle simple token", () => {
      expect(marginClasses("md")).toBe("m-4");
    });

    it("should handle x/y shorthand", () => {
      expect(marginClasses({ x: "md" })).toBe("mx-4");
    });

    it("should handle individual sides", () => {
      expect(marginClasses({ bottom: "sm" })).toBe("mb-2");
    });
  });

  describe("textColorClass", () => {
    it("should map color tokens", () => {
      expect(textColorClass("primary")).toBe("text-primary");
      expect(textColorClass("muted")).toBe("text-muted-foreground");
      expect(textColorClass("danger")).toBe("text-destructive");
    });

    it("should pass through custom values", () => {
      expect(textColorClass("#ff0000")).toBe("text-[#ff0000]");
    });
  });

  describe("bgColorClass", () => {
    it("should map color tokens", () => {
      expect(bgColorClass("primary")).toBe("bg-primary");
      expect(bgColorClass("muted")).toBe("bg-muted");
    });
  });

  describe("radiusClass", () => {
    it("should map radius tokens", () => {
      expect(radiusClass("none")).toBe("rounded-none");
      expect(radiusClass("sm")).toBe("rounded-sm");
      expect(radiusClass("md")).toBe("rounded-md");
      expect(radiusClass("lg")).toBe("rounded-lg");
      expect(radiusClass("full")).toBe("rounded-full");
    });
  });

  describe("resolveTypography", () => {
    it("should resolve heading-1", () => {
      const result = resolveTypography("heading-1");
      expect(result.element).toBe("h1");
      expect(result.classes).toContain("text-2xl");
      expect(result.classes).toContain("font-bold");
    });

    it("should resolve body", () => {
      const result = resolveTypography("body");
      expect(result.element).toBe("p");
      expect(result.classes).toContain("text-sm");
    });

    it("should resolve caption", () => {
      const result = resolveTypography("caption");
      expect(result.element).toBe("span");
      expect(result.classes).toContain("text-xs");
    });
  });

  describe("alignClass / justifyClass", () => {
    it("should map alignment values", () => {
      expect(alignClass("center")).toBe("items-center");
      expect(alignClass("start")).toBe("items-start");
      expect(justifyClass("between")).toBe("justify-between");
      expect(justifyClass("center")).toBe("justify-center");
    });
  });

  describe("iconSizeClass", () => {
    it("should map icon sizes", () => {
      expect(iconSizeClass("sm")).toBe("h-4 w-4");
      expect(iconSizeClass("md")).toBe("h-5 w-5");
      expect(iconSizeClass("lg")).toBe("h-6 w-6");
    });
  });

  describe("avatarSizeClass", () => {
    it("should map avatar sizes", () => {
      expect(avatarSizeClass("sm")).toBe("h-6 w-6");
      expect(avatarSizeClass("md")).toBe("h-8 w-8");
      expect(avatarSizeClass("xl")).toBe("h-14 w-14");
    });
  });

  describe("buildClasses", () => {
    it("should join truthy values and filter falsy", () => {
      expect(buildClasses(["flex", "gap-4", false, undefined, "p-2", null])).toBe(
        "flex gap-4 p-2"
      );
    });

    it("should return empty string for all falsy", () => {
      expect(buildClasses([false, undefined, null])).toBe("");
    });
  });

  describe("reverse mapping", () => {
    it("should reverse spacing tokens", () => {
      expect(tailwindToSpacing("1")).toBe("xs");
      expect(tailwindToSpacing("4")).toBe("md");
      expect(tailwindToSpacing("6")).toBe("lg");
      expect(tailwindToSpacing("99")).toBeUndefined();
    });

    it("should reverse radius tokens", () => {
      expect(tailwindToRadius("rounded-md")).toBe("md");
      expect(tailwindToRadius("rounded-full")).toBe("full");
      expect(tailwindToRadius("rounded-xl")).toBeUndefined();
    });
  });
});
