import { describe, expect, it, vi, afterEach } from "vitest";
import {
  IMAGE_MAX_BYTES,
  describeFit,
  formatBytes,
  isImageFile,
  readImageDimensions,
  readImageUrl,
  slotSizeFor,
  validateImageFile,
  writeImageUrl,
} from "./image-asset";

const file = (name: string, type: string, size = 1024) => ({ name, type, size });

describe("validateImageFile", () => {
  it("accepts the four media types the backend classify() accepts", () => {
    for (const [name, type] of [
      ["a.png", "image/png"],
      ["a.jpg", "image/jpeg"],
      ["a.gif", "image/gif"],
      ["a.webp", "image/webp"],
    ] as const) {
      expect(validateImageFile(file(name, type)).ok, `${type}`).toBe(true);
    }
  });

  it("accepts image/jpg, which browsers send but is not a real media type", () => {
    expect(validateImageFile(file("shot.jpg", "image/jpg")).ok).toBe(true);
  });

  it("falls back to the extension when the type is missing (pasted screenshots)", () => {
    expect(validateImageFile(file("screenshot.png", "")).ok).toBe(true);
    expect(validateImageFile(file("screenshot.PNG", "")).ok).toBe(true);
  });

  it("rejects a PDF with a message naming the file and the allowed types", () => {
    const v = validateImageFile(file("spec.pdf", "application/pdf"));
    expect(v.ok).toBe(false);
    if (v.ok) return;
    expect(v.reason).toBe("type");
    expect(v.message).toContain("spec.pdf");
    expect(v.message).toMatch(/PNG/);
  });

  it("rejects SVG — chat_attachments does not list it either", () => {
    expect(validateImageFile(file("icon.svg", "image/svg+xml")).ok).toBe(false);
  });

  it("rejects an empty file before anything tries to decode it", () => {
    const v = validateImageFile(file("empty.png", "image/png", 0));
    expect(v.ok).toBe(false);
    if (!v.ok) expect(v.reason).toBe("empty");
  });

  it("rejects over the 10 MB backend limit and passes exactly at it", () => {
    expect(validateImageFile(file("big.png", "image/png", IMAGE_MAX_BYTES)).ok).toBe(true);
    const v = validateImageFile(file("big.png", "image/png", IMAGE_MAX_BYTES + 1));
    expect(v.ok).toBe(false);
    if (!v.ok) {
      expect(v.reason).toBe("size");
      expect(v.message).toContain("10 MB");
    }
  });

  it("agrees with the backend that a text/* type is not an image", () => {
    expect(isImageFile("notes.png", "text/plain")).toBe(false);
  });
});

describe("formatBytes", () => {
  it("scales the unit", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(20166)).toBe("20 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});

describe("readImageDimensions", () => {
  const realImage = globalThis.Image;
  afterEach(() => { globalThis.Image = realImage; });

  function stubImage(behaviour: (img: any) => void) {
    globalThis.Image = class {
      naturalWidth = 0;
      naturalHeight = 0;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_v: string) { setTimeout(() => behaviour(this), 0); }
    } as unknown as typeof Image;
  }

  it("resolves the decoded natural size", async () => {
    stubImage((img) => { img.naturalWidth = 120; img.naturalHeight = 80; img.onload?.(); });
    await expect(readImageDimensions("blob:x")).resolves.toEqual({ width: 120, height: 80 });
  });

  it("rejects when the image fails to load", async () => {
    stubImage((img) => img.onerror?.());
    await expect(readImageDimensions("http://nope/x.png")).rejects.toThrow(/couldn't load/i);
  });

  it("rejects an empty src rather than hanging", async () => {
    await expect(readImageDimensions("")).rejects.toThrow(/no image source/);
  });

  it("times out instead of leaving the caller waiting forever", async () => {
    vi.useFakeTimers();
    stubImage(() => { /* never settles */ });
    const p = readImageDimensions("http://slow/x.png", 50);
    const assertion = expect(p).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(60);
    await assertion;
    vi.useRealTimers();
  });
});

describe("slotSizeFor", () => {
  it("reads Avatar's SIZE_CLASS pixel sizes off the size prop", () => {
    expect(slotSizeFor("Avatar", "photoUrl", { size: "sm" })).toMatchObject({ width: 32, height: 32 });
    expect(slotSizeFor("Avatar", "photoUrl", { size: "md" })).toMatchObject({ width: 40, height: 40 });
    expect(slotSizeFor("Avatar", "photoUrl", { size: "lg" })).toMatchObject({ width: 64, height: 64 });
  });

  it("reports md for xs/xl, which SIZE_CLASS has no entry for and falls back on", () => {
    expect(slotSizeFor("Avatar", "photoUrl", { size: "xl" })).toMatchObject({ width: 40 });
  });

  it("covers Avatar's legacy src prop too", () => {
    expect(slotSizeFor("Avatar", "src", { size: "lg" })).toMatchObject({ width: 64 });
  });

  it("switches PersonCard on layout", () => {
    expect(slotSizeFor("PersonCard", "avatarUrl", {})).toMatchObject({ width: 40 });
    expect(slotSizeFor("PersonCard", "avatarUrl", { layout: "expanded" })).toMatchObject({ width: 64 });
  });

  it("says fluid for Hero rather than inventing a recommended width", () => {
    const bg = slotSizeFor("Hero", "backgroundImage", {});
    expect(bg?.fit).toBe("fluid");
    expect(bg?.width).toBeUndefined();
    expect(slotSizeFor("Hero", "media", {})?.fit).toBe("fluid");
  });

  it("returns null for a component with no known image geometry", () => {
    expect(slotSizeFor("Card", "photoUrl", {})).toBeNull();
  });
});

describe("describeFit", () => {
  const avatarMd = slotSizeFor("Avatar", "photoUrl", { size: "md" })!;

  it("states the rendered size", () => {
    expect(describeFit({ width: 200, height: 200 }, avatarMd)).toContain("40x40");
  });

  it("warns when the image is below 2x the slot", () => {
    expect(describeFit({ width: 40, height: 40 }, avatarMd)).toContain("80x80");
  });

  it("stays quiet about sharpness at 2x or better", () => {
    expect(describeFit({ width: 80, height: 80 }, avatarMd)).not.toMatch(/sharp/);
  });

  it("names the crop direction for a mismatched aspect ratio", () => {
    expect(describeFit({ width: 400, height: 100 }, avatarMd)).toMatch(/sides will be cropped/);
    expect(describeFit({ width: 100, height: 400 }, avatarMd)).toMatch(/top and bottom will be cropped/);
  });

  it("describes a fluid slot without pretending it has pixels", () => {
    const hero = slotSizeFor("Hero", "backgroundImage", {})!;
    const s = describeFit({ width: 1600, height: 900 }, hero)!;
    expect(s).toContain("cover");
    expect(s).not.toMatch(/\d+x\d+/);
  });

  it("says nothing when either side is unknown", () => {
    expect(describeFit(null, avatarMd)).toBeNull();
    expect(describeFit({ width: 10, height: 10 }, null)).toBeNull();
  });
});

describe("readImageUrl / writeImageUrl", () => {
  it("round-trips a bare url prop", () => {
    expect(readImageUrl("/api/asset/x/figma/a.png", "url")).toBe("/api/asset/x/figma/a.png");
    expect(writeImageUrl("old", "url", "new")).toBe("new");
  });

  it("reads and writes Hero.backgroundImage's { url, overlay }", () => {
    const cur = { url: "old.png", overlay: 0.7 };
    expect(readImageUrl(cur, "overlay")).toBe("old.png");
    expect(writeImageUrl(cur, "overlay", "new.png")).toEqual({ url: "new.png", overlay: 0.7 });
  });

  it("defaults overlay when the prop was empty", () => {
    expect(writeImageUrl(null, "overlay", "new.png")).toEqual({ url: "new.png", overlay: 0.4 });
  });

  it("reads and writes Hero.media's { kind, src, alt }", () => {
    const cur = { kind: "image", src: "old.png", alt: "a cat" };
    expect(readImageUrl(cur, "media")).toBe("old.png");
    expect(writeImageUrl(cur, "media", "new.png")).toEqual({ kind: "image", src: "new.png", alt: "a cat" });
  });

  it("defaults kind to image when the prop was empty", () => {
    expect(writeImageUrl(undefined, "media", "n.png")).toEqual({ kind: "image", src: "n.png", alt: "" });
  });

  it("clears object props to undefined, not to { url: '' } which the schema rejects", () => {
    expect(writeImageUrl({ url: "a", overlay: 0.4 }, "overlay", "")).toBeUndefined();
    expect(writeImageUrl({ kind: "image", src: "a" }, "media", "")).toBeUndefined();
    expect(writeImageUrl("a", "url", "")).toBe("");
  });

  it("returns an empty string rather than throwing on a wrong-shaped value", () => {
    expect(readImageUrl({ nope: 1 }, "overlay")).toBe("");
    expect(readImageUrl(42, "url")).toBe("");
    expect(readImageUrl(null, "media")).toBe("");
  });
});
