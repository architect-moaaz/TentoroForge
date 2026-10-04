import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";
import { chipSuppressed, isEmptyFileRoute, isPendingSrc, isUsableSrc, photoMessage, resolveSrc, situationFor, splitClasses } from "../src/nodes/primitive/Image";

const img = (props: any) => ({ id: "i", type: "Image", props });
const html = (props: any, user?: any) => renderToString(renderNode(img(props) as any, { data: {}, user } as any));

describe("a photo that is not there", () => {
  it("draws a tile with the item's initial, not a blank box or nothing", () => {
    const h = html({ src: "", alt: "Iced Lemon Tea" });
    expect(h).toContain('data-photo-placeholder="none"');
    expect(h).toContain(">I<");
    expect(h).toContain("Iced Lemon Tea");
    expect(h).not.toContain("<img");
  });
  it("treats an unresolved binding or an empty file route as no photo", () => {
    expect(isUsableSrc("{{item.image}}")).toBe(false);
    expect(isUsableSrc("/api/files/")).toBe(false);
    expect(isUsableSrc(undefined)).toBe(false);
    expect(isUsableSrc("https://x/y.jpg")).toBe(true);
  });
  it("tells only editors to add one by editing", () => {
    expect(html({ src: "", alt: "A" }, { role: "admin" })).toContain("add one by editing this item");
    expect(html({ src: "", alt: "A" }, { role: "customer" })).not.toContain("editing");
    expect(html({ src: "", alt: "A" })).not.toContain("editing");
  });
  it("says a failed load could not be loaded, and placeholder text is no photo, not a failed load", () => {
    expect(photoMessage("broken", true).reason).toBe("Photo couldn't be loaded");
    expect(isUsableSrc("Image Url 1")).toBe(false);
    expect(html({ src: "Image Url 1", alt: "A" })).toContain('data-photo-placeholder="none"');
    expect(isUsableSrc("data:image/png;base64,AAAA")).toBe(true);
  });
  it("shows the photographer's credit and strips it from the address", () => {
    const h = html({ src: "https://images.unsplash.com/x?w=1#credit=Ann%20Lee&credit_link=https%3A%2F%2Fu%2Fann", alt: "T" });
    expect(h).toContain('src="https://images.unsplash.com/x?w=1"');
    expect(h).toContain("Photo by Ann Lee on Unsplash");
  });
  it("a real photo is still an img, an icon with no asset stays empty", () => {
    expect(html({ src: "/x.png", alt: "x" })).toContain('src="/x.png"');
    expect(renderToString(renderNode({ id: "ic", type: "Icon", props: {} } as any, { data: {} } as any))).toBe("");
  });

  it("accepts every address shape the apps use and still rejects plain text", () => {
    for (const ok of ["assets/hero.png", "./x.png", "../img/a.JPG?w=2", "//cdn.x/y.png", "blob:http://h/abc", "data:image/png;base64,AA",
                      "/api/files/abc.png", "https://images.unsplash.com/x?w=1", "3f2b8c1e-1111-4222-8333-444455556666"]) {
      expect(isUsableSrc(ok), ok).toBe(true);
    }
    for (const bad of ["Image Url 1", "", "   ", "undefined", "/api/files/", "{{item.imageUrl}}", "hello world.png"]) {
      expect(isUsableSrc(bad), bad).toBe(false);
    }
    expect(resolveSrc("3f2b8c1e-1111-4222-8333-444455556666")).toBe("/api/files/preview?src=3f2b8c1e-1111-4222-8333-444455556666");
  });
  it("an unresolved binding is 'not known yet': no reason and no edit hint", () => {
    expect(isPendingSrc("/api/files/{{scan.imageUrl}}")).toBe(true);
    expect(isEmptyFileRoute("/api/files/")).toBe(true);                       // pending only within the grace (first render)
    const h = html({ src: "/api/files/{{scan.imageUrl}}", alt: "Scan" }, { role: "admin" });
    expect(h).toContain('data-photo-placeholder="pending"');
    expect(h).not.toContain("editing");
  });
  it("shows a visible, linked credit over the picture and can be hidden", () => {
    const src = "https://images.unsplash.com/x?w=1#credit=Ann%20Lee&credit_link=https%3A%2F%2Funsplash.com%2F%40ann%3Futm_source%3Dtentoro_forge";
    const h = html({ src, alt: "T", className: "w-full" });
    expect(h).toContain("data-photo-credit");
    expect(h).toContain("Photo by");
    expect(h).toContain('href="https://unsplash.com/@ann?utm_source=tentoro_forge"');
    expect(h).toContain("Ann Lee");
    expect(html({ src, alt: "T", showCredit: false })).not.toContain("data-photo-credit");
  });

  it("an empty file route is 'loading' only for a short grace, then genuinely 'No photo yet'", () => {
    expect(isEmptyFileRoute("/api/files/")).toBe(true);
    expect(situationFor("/api/files/", false, true)).toBe("pending");
    expect(situationFor("/api/files/", false, false)).toBe("none");               // known empty: reason + edit hint
    expect(situationFor("/api/files/{{x.imageUrl}}", false, false)).toBe("pending"); // unresolved in the string: stays quiet
    expect(situationFor("", false, false)).toBe("none");
    expect(situationFor("x", true, false)).toBe("broken");
  });
  it("the credit chip is for big pictures only; round and small ones keep the tooltip", () => {
    expect(chipSuppressed("h-10 w-10 rounded-full object-cover", undefined, undefined)).toBe(true);
    expect(chipSuppressed("h-10 w-10 rounded-md", undefined, undefined)).toBe(true);
    expect(chipSuppressed("object-cover", 40, 40)).toBe(true);
    expect(chipSuppressed("h-24 w-24 object-cover", undefined, undefined)).toBe(false);   // 96px
    expect(chipSuppressed("h-full w-full object-cover", undefined, undefined)).toBe(false);
    const src = "https://images.unsplash.com/x?w=1#credit=Ann%20Lee&credit_link=https%3A%2F%2Fu%2Fann";
    expect(html({ src, alt: "T", className: "h-10 w-10 rounded-full" })).not.toContain("data-photo-credit");
    expect(html({ src, alt: "T", className: "h-10 w-10 rounded-full" })).toContain("Photo by Ann Lee on Unsplash");   // tooltip
  });
  it("the wrapper takes the image's layout classes so the wrapped image is the same box", () => {
    const { wrapper, img, sized } = splitClasses("h-full w-full object-cover rounded-md aspect-video");
    expect(sized).toBe(true);
    for (const c of ["h-full", "w-full", "rounded-md", "aspect-video"]) expect(wrapper).toContain(c);
    expect(img).toContain("object-cover");
    expect(img.split(" ")).toContain("h-full");
    expect(splitClasses("object-cover").sized).toBe(false);
  });
});
