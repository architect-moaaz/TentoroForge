/**
 * Pure helpers behind the properties panel's image control: what counts as an
 * image, how big is too big, how many pixels the file actually has, and how
 * many pixels the slot it is going into will actually paint.
 *
 * Kept free of React and of `fetch` so every rule here is unit-testable and so
 * the control has no logic worth hiding.
 */

/**
 * Mirror of `backend/services/chat_attachments.MAX_BYTES` (10 MB).
 *
 * Duplicated rather than fetched because the point of the client-side check is
 * to refuse a 40 MB drop BEFORE it goes over the wire — a limit you have to ask
 * the server for cannot do that. The server still enforces its own copy, so a
 * drift makes the client permissive, never the storage.
 */
export const IMAGE_MAX_BYTES = 10 * 1024 * 1024;

/**
 * Mirror of `chat_attachments._IMAGE_MEDIA`. SVG is deliberately absent there
 * and deliberately absent here: an SVG is a script carrier, and admitting one
 * is a security decision for the backend to make, not a convenience the
 * control can grant on its own.
 */
export const ACCEPTED_IMAGE_MEDIA = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
] as const;

/** Mirror of `chat_attachments._IMAGE_EXT`. */
export const ACCEPTED_IMAGE_EXT = [".png", ".jpg", ".jpeg", ".gif", ".webp"] as const;

/** `accept` attribute for the click-to-browse `<input type="file">`. */
export const IMAGE_ACCEPT_ATTR = [...ACCEPTED_IMAGE_EXT, ...ACCEPTED_IMAGE_MEDIA].join(",");

// Browsers send `image/jpg`, which is not a real media type. chat_attachments
// normalises the same two aliases; if we did not, a drag-drop from some
// Windows apps would be refused here and accepted by the server.
const MEDIA_ALIASES: Record<string, string> = {
  "image/jpg": "image/jpeg",
  "image/pjpeg": "image/jpeg",
};

export type ImageRejection = "empty" | "type" | "size";

export type ImageValidation =
  | { ok: true }
  | { ok: false; reason: ImageRejection; message: string };

function extensionOf(name: string): string {
  const i = (name || "").lastIndexOf(".");
  return i < 0 ? "" : name.slice(i).toLowerCase();
}

export function normalizeMediaType(contentType: string): string {
  const ct = (contentType || "").toLowerCase().trim();
  return MEDIA_ALIASES[ct] ?? ct;
}

/** True when `chat_attachments.classify()` would call this file an image. */
export function isImageFile(name: string, contentType: string): boolean {
  const ct = normalizeMediaType(contentType);
  if ((ACCEPTED_IMAGE_MEDIA as readonly string[]).includes(ct)) return true;
  // Content type wins when decisive, extension is the fallback — same order as
  // classify(), because a pasted screenshot often has neither a real name nor
  // a trustworthy type and we must agree with the server on which one wins.
  if (ct && ct !== "application/octet-stream" && !ct.startsWith("image/")) return false;
  return (ACCEPTED_IMAGE_EXT as readonly string[]).includes(extensionOf(name));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Decide, without touching the network, whether this file may be uploaded.
 * The `message` is written to be shown to the user verbatim.
 */
export function validateImageFile(file: { name: string; type: string; size: number }): ImageValidation {
  if (!file.size) {
    return { ok: false, reason: "empty", message: `${file.name || "That file"} is empty.` };
  }
  if (!isImageFile(file.name, file.type)) {
    return {
      ok: false,
      reason: "type",
      message: `${file.name || "That file"} isn't an image — drop a PNG, JPEG, GIF or WebP.`,
    };
  }
  if (file.size > IMAGE_MAX_BYTES) {
    return {
      ok: false,
      reason: "size",
      message: `${file.name} is ${formatBytes(file.size)} — the limit is ${
        IMAGE_MAX_BYTES / 1024 / 1024
      } MB.`,
    };
  }
  return { ok: true };
}

export interface PixelSize {
  width: number;
  height: number;
}

/**
 * The image's real pixel dimensions, read by decoding it in the browser.
 *
 * Works for an object URL (a file the user just dropped, measured before the
 * upload even starts) AND for an http(s) or `/api/asset/...` URL the user typed
 * by hand — which is why dimensions are read here rather than parsed out of the
 * file header on the server: the typed-URL path has no upload to parse.
 */
export function readImageDimensions(src: string, timeoutMs = 15_000): Promise<PixelSize> {
  return new Promise((resolve, reject) => {
    if (!src) {
      reject(new Error("no image source"));
      return;
    }
    const img = new Image();
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      img.onload = img.onerror = null;
      reject(new Error("timed out loading image"));
    }, timeoutMs);
    const done = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      img.onload = img.onerror = null;
      fn();
    };
    img.onload = () =>
      done(() => resolve({ width: img.naturalWidth || img.width, height: img.naturalHeight || img.height }));
    img.onerror = () => done(() => reject(new Error("couldn't load that image")));
    img.src = src;
  });
}

/* ------------------------------------------------------------------ *
 * How big the slot actually is
 * ------------------------------------------------------------------ */

export interface SlotSize {
  /** CSS pixels the component paints the image at, when it pins a size. */
  width?: number;
  height?: number;
  /** How the browser fits the image into that box. */
  fit: "cover" | "contain" | "fluid";
  /** Short description of the slot, shown next to the measurement. */
  note: string;
}

/**
 * What the component will actually do with the image, read off the library's
 * own CSS rather than guessed.
 *
 * Only components whose markup pins a size can answer in pixels; the rest get
 * a `fluid` answer, because inventing a "recommended 1600px" for a
 * `background-size: cover` hero would be advice this codebase cannot back up.
 *
 * Sources (keep in sync if the library's classes change):
 *   Avatar      packages/library/src/components/Avatar/Avatar.tsx  SIZE_CLASS
 *               sm h-8 (32) · md h-10 (40) · lg h-16 (64); the registry also
 *               offers xs/xl but SIZE_CLASS has no entry for them and falls
 *               back to md, so we report 40 for those too rather than a size
 *               the component never renders.
 *   PersonCard  packages/library/src/components/PersonCard/PersonCard.tsx
 *               compact h-10 w-10 (40) · expanded h-16 w-16 (64)
 *   Hero        packages/library/src/components/Hero/Hero.tsx
 *               backgroundImage → background-size: cover on the whole section
 *               media           → <img class="w-full h-auto object-cover">
 */
export function slotSizeFor(
  nodeType: string | undefined,
  propName: string,
  nodeProps: Record<string, unknown> | undefined,
): SlotSize | null {
  const props = nodeProps ?? {};

  if (nodeType === "Avatar" && (propName === "photoUrl" || propName === "src")) {
    const size = String(props.size ?? "md");
    const px = size === "sm" ? 32 : size === "lg" ? 64 : 40;
    return { width: px, height: px, fit: "cover", note: `Avatar size "${size}"` };
  }

  if (nodeType === "PersonCard" && propName === "avatarUrl") {
    const px = props.layout === "expanded" ? 64 : 40;
    return { width: px, height: px, fit: "cover", note: `PersonCard layout "${props.layout ?? "compact"}"` };
  }

  if (nodeType === "Hero" && propName === "backgroundImage") {
    return { fit: "fluid", note: "fills the hero (background-size: cover) — no fixed size" };
  }

  if (nodeType === "Hero" && propName === "media") {
    return { fit: "fluid", note: "spans the media column (width: 100%, height auto)" };
  }

  return null;
}

/**
 * One sentence telling the user whether their image suits the slot — the whole
 * point of showing dimensions at all. Returns null when there is nothing
 * useful to say.
 */
export function describeFit(image: PixelSize | null, slot: SlotSize | null): string | null {
  if (!image) return null;
  if (!slot) return null;

  if (slot.fit === "fluid" || slot.width === undefined || slot.height === undefined) {
    return `Slot ${slot.note}.`;
  }

  // A cover slot crops to its own aspect ratio, so "too small" and "wrong
  // shape" are different complaints and the user needs to hear both.
  const parts: string[] = [`Slot renders at ${slot.width}x${slot.height} (cover).`];

  // 2x is the retina target, not a preference: a 40px avatar on a 2x display
  // paints 80 device pixels, and a 40px source visibly softens there.
  const need = { w: slot.width * 2, h: slot.height * 2 };
  if (image.width < need.w || image.height < need.h) {
    parts.push(`Below the ${need.w}x${need.h} needed to stay sharp on a 2x display.`);
  }

  const imgAr = image.width / image.height;
  const slotAr = slot.width / slot.height;
  if (Math.abs(imgAr - slotAr) / slotAr > 0.1) {
    parts.push(
      imgAr > slotAr
        ? "Wider than the slot — the sides will be cropped."
        : "Taller than the slot — the top and bottom will be cropped.",
    );
  }

  return parts.join(" ");
}

/* ------------------------------------------------------------------ *
 * Reading and writing the prop value
 * ------------------------------------------------------------------ */

/**
 * The JSON shape a given image prop stores its URL in. Declared on the prop in
 * `packages/registry/src/starter.ts` (`PropDescriptor.imageShape`) rather than
 * inferred from the prop's name here, so adding an image prop to a component
 * is a registry edit and not a second edit to a name list in the editor.
 *
 *   "url"     — the prop IS the url string (Avatar.photoUrl, PersonCard.avatarUrl)
 *   "overlay" — { url, overlay }        (Hero.backgroundImage, schema foundation.ts:44)
 *   "media"   — { kind, src, alt }      (Hero.media, schema foundation.ts:16)
 */
export type ImageShape = "url" | "overlay" | "media";

/** The URL currently held by an image prop, whatever shape it is stored in. */
export function readImageUrl(value: unknown, shape: ImageShape): string {
  if (shape === "url") return typeof value === "string" ? value : "";
  if (!value || typeof value !== "object") return "";
  const key = shape === "overlay" ? "url" : "src";
  const v = (value as Record<string, unknown>)[key];
  return typeof v === "string" ? v : "";
}

/**
 * The new prop value for `url`, preserving every sibling field the shape
 * carries. Clearing the URL clears the whole prop — a `{ url: "" }` fails the
 * schema's `z.string().min(1)` (foundation.ts:45), so an empty object is not a
 * legal "no image" and `undefined` is.
 */
export function writeImageUrl(current: unknown, shape: ImageShape, url: string): unknown {
  if (!url) return shape === "url" ? "" : undefined;
  if (shape === "url") return url;
  const base = current && typeof current === "object" ? { ...(current as Record<string, unknown>) } : {};
  if (shape === "overlay") {
    return { overlay: 0.4, ...base, url };
  }
  return { kind: "image", alt: "", ...base, src: url };
}
