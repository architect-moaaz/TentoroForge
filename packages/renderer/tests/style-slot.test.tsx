import { describe, it, expect } from "vitest";
import { applyStyleSlot } from "../src/runtime/style-slot";

describe("applyStyleSlot position", () => {
  it("returns no position keys for legacy styleSlot", () => {
    const result = applyStyleSlot({ spacing: { padding: "md" } } as any);
    expect(result.style?.position).toBeUndefined();
    expect((result.style as any)?.top).toBeUndefined();
  });

  it("emits position:absolute when set", () => {
    const result = applyStyleSlot({
      position: { type: "absolute", top: "16px", right: "24px" },
    } as any);
    expect(result.style?.position).toBe("absolute");
    expect((result.style as any)?.top).toBe("16px");
    expect((result.style as any)?.right).toBe("24px");
  });

  it("emits zIndex when set", () => {
    const result = applyStyleSlot({
      position: { type: "absolute", zIndex: 10 },
    } as any);
    expect((result.style as any)?.zIndex).toBe(10);
  });

  it("emits sticky and fixed correctly", () => {
    const sticky = applyStyleSlot({ position: { type: "sticky", top: "0" } } as any);
    expect(sticky.style?.position).toBe("sticky");
    const fixed = applyStyleSlot({ position: { type: "fixed", bottom: "0", left: "0" } } as any);
    expect(fixed.style?.position).toBe("fixed");
  });
});
