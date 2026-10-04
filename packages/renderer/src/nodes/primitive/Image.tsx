"use client";
import { useEffect, useRef, useState } from "react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

/** Roles that may edit an item, so only they are told to "add one by editing". */
const EDITOR_ROLE = /^(admin|owner|manager|editor|staff|superadmin|super_admin)$/i;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|avif|svg|bmp|ico)(\?.*)?(#.*)?$/i;

/** The address to load: a stored file id (an upload) goes through the app's file
 *  preview route, exactly as the library's `fileSrc` does; anything else as is. */
export function resolveSrc(src: string): string {
  const s = src.trim();
  return UUID_RE.test(s) ? `/api/files/preview?src=${encodeURIComponent(s)}` : s;
}

/** A src that points at something loadable: an http(s) or protocol-relative
 *  address, a root-relative path, a blob:/image data: URI, a stored file id, or a
 *  relative path to an image file (`assets/hero.png`, `./x.png`). Empty, text
 *  that is not an address ("Image Url 1") or a file route with no file id
 *  (`/api/files/`) is nothing - the page shows "No photo yet", not a failed load.
 *  An unresolved `{{binding}}` is "not known yet" (see `isPendingSrc`). */
export function isUsableSrc(src: unknown): src is string {
  if (typeof src !== "string") return false;
  const s = src.trim();
  if (!s || s.includes("{{")) return false;
  if (UUID_RE.test(s)) return true;
  if (/^(https?:\/\/|\/\/|blob:|data:image\/)/i.test(s)) return true;
  if (s.startsWith("/")) return !/\/$/.test(s.split("#")[0]);
  return IMAGE_EXT.test(s) && /^[\w.\-\/~%@+]+/.test(s) && !/\s/.test(s.split("?")[0]);
}

/** An unresolved `{{binding}}` still IN the src string: the engine/editor preview has not
 *  resolved it, so the value is not known (and never will be here). */
export function isPendingSrc(src: unknown): boolean {
  return typeof src === "string" && src.includes("{{");
}

/** A file route whose id came out empty ("/api/files/" from "/api/files/{{x.imageUrl}}"): the
 *  schema renderer drops an unresolved binding to "", so the page cannot tell "not loaded yet"
 *  from "this record has no photo". It is treated as "loading" only for a short grace after mount
 *  (the quiet tile), then as genuinely empty ("No photo yet", with the edit hint for editors). */
export function isEmptyFileRoute(src: unknown): boolean {
  return typeof src === "string" && /^\/api\/files\/?$/.test(src.trim());
}

/** What an unusable src is, right now. */
export function situationFor(src: unknown, failed: boolean, inGrace: boolean): PhotoSituation {
  if (failed) return "broken";
  if (isPendingSrc(src) || (isEmptyFileRoute(src) && inGrace)) return "pending";
  return "none";
}

/** How long an empty file route reads as "still loading" before it reads as "no photo". */
export const GRACE_MS = 1500;

/** A photo's credit travels in the address after `#credit=`: the browser never
 *  sends a fragment, so the picture is unchanged; the licence's "Photo by ..."
 *  is read from it. */
export function splitCredit(src: string): { url: string; credit?: { name: string; link?: string } } {
  const i = src.indexOf("#credit=");
  if (i < 0) return { url: src };
  // A malformed escape ("%E0%A4%A", a lone "%") must never throw during render: URLSearchParams
  // decodes leniently, and anything that still fails reads as "no credit" (the address is kept).
  try {
    const q = new URLSearchParams(src.slice(i + 1));
    const name = (q.get("credit") ?? "").trim();
    return { url: src.slice(0, i), credit: name ? { name, link: q.get("credit_link") || undefined } : undefined };
  } catch {
    return { url: src.slice(0, i) };
  }
}

export type PhotoSituation = "none" | "broken" | "pending";

const LAYOUT_TOKEN = /^(?:[a-z0-9-]+:)*-?(?:w|h|min-w|min-h|max-w|max-h|size|aspect|basis|grow|shrink|flex|col|row|self|place-self|justify-self|order|m|mx|my|mt|mr|mb|ml|absolute|relative|fixed|sticky|inset|top|left|right|bottom|z|float)(?:-|$)/;
const SIZING_TOKEN = /^(?:[a-z0-9-]+:)*(?:w|h|size|aspect|min-w|min-h)-/;
const SHAPE_TOKEN = /^(?:[a-z0-9-]+:)*rounded/;
const ROUND_FULL = /(?:^|\s)(?:[a-z0-9-]+:)*rounded-full(?:\s|$)|avatar/i;
/** A rendered picture smaller than this carries its credit in a tooltip only. */
export const CHIP_MIN_PX = 64;

/** The wrapper takes the image's LAYOUT classes (size, aspect, position, margin) and
 *  its rounding; the image inside fills it, so wrapped and unwrapped are the same box. */
export function splitClasses(cls: string | undefined): { wrapper: string; img: string; sized: boolean } {
  const tokens = (cls ?? "").split(/\s+/).filter(Boolean);
  const wrapper = tokens.filter((c) => LAYOUT_TOKEN.test(c) || SHAPE_TOKEN.test(c));
  const img = tokens.filter((c) => !LAYOUT_TOKEN.test(c));
  const sized = tokens.some((c) => SIZING_TOKEN.test(c));
  return { wrapper: wrapper.join(" "), img: (sized ? ["h-full", "w-full", ...img] : img).join(" "), sized };
}

/** Too small, or round, for a credit chip: a 40px avatar or a table thumbnail. */
export function chipSuppressed(cls: string | undefined, width: unknown, height: unknown): boolean {
  if (ROUND_FULL.test(cls ?? "")) return true;
  const px = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && /^\d+(px)?$/.test(v) ? parseInt(v, 10) : NaN);
  if (px(width) < CHIP_MIN_PX || px(height) < CHIP_MIN_PX) return true;
  return (cls ?? "").split(/\s+/).some((c) => {
    const m = /^(?:[a-z0-9-]+:)*(?:w|h|size)-(\d+(?:\.\d+)?)$/.exec(c);
    return !!m && parseFloat(m[1]) * 4 < CHIP_MIN_PX;          // Tailwind: N * 0.25rem = N * 4px
  });
}

/** What the person is told, by situation. The edit hint is for editors only. */
export function photoMessage(situation: PhotoSituation, canEdit: boolean): { title: string; reason: string } {
  // Not known yet: no reason and no edit hint until the value is known to be empty.
  if (situation === "pending") return { title: "Photo not loaded yet", reason: "" };
  if (situation === "broken") return { title: "No photo", reason: "Photo couldn't be loaded" };
  return {
    title: "No photo yet",
    reason: canEdit ? "No photo yet - add one by editing this item" : "No photo yet",
  };
}

function initialOf(text: unknown): string {
  const t = typeof text === "string" ? text.trim() : "";
  return t ? t[0].toUpperCase() : "";
}

/**
 * A designed stand-in for a photo that is not there: a tile tinted with the
 * app's brand colour, the item's initial, and one calm line saying why.
 * Never a broken-image icon, never a blank white box.
 */
export function PhotoPlaceholder({ label, situation, canEdit, className, style, width, height, nodeId }: {
  label?: string; situation: PhotoSituation; canEdit: boolean;
  className?: string; style?: React.CSSProperties; width?: number | string; height?: number | string; nodeId?: string;
}) {
  const { title, reason } = photoMessage(situation, canEdit);
  const initial = initialOf(label);
  const aria = `${title}${label ? ` for ${label}` : ""}. ${reason}`;
  return (
    <div
      role="img"
      aria-label={aria}
      data-node-id={nodeId}
      data-photo-placeholder={situation}
      className={className}
      style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 6, padding: 8, textAlign: "center", overflow: "hidden", boxSizing: "border-box",
        minHeight: 96, width: width ?? "100%", height,
        background: "color-mix(in oklch, var(--color-primary, #6b7280) 12%, var(--color-card, #ffffff))",
        color: "var(--color-primary, #4b5563)",
        ...style,
      }}
    >
      <span aria-hidden="true" style={{ fontSize: 28, fontWeight: 600, lineHeight: 1 }}>{initial || "▣"}</span>
      {reason && <span style={{ fontSize: 11, lineHeight: 1.3, opacity: 0.8, maxWidth: "22ch" }}>{reason}</span>}
    </div>
  );
}

export function Image({ node, user, decorative }: { node: any; user?: Record<string, unknown>; decorative?: boolean }) {
  const p = node.props ?? {};
  const { src, alt, width, height } = p;
  const [failed, setFailed] = useState<string | null>(null);
  const [inGrace, setInGrace] = useState(() => isEmptyFileRoute(src));
  const [chipFits, setChipFits] = useState(true);
  const holder = useRef<HTMLSpanElement | null>(null);
  // The grace is for ONE case - an empty file route - so a normal image sets no timer at all; it is
  // cancelled when a usable src arrives or on unmount.
  const emptyRoute = isEmptyFileRoute(src);
  useEffect(() => {
    if (!emptyRoute) return;
    setInGrace(true);
    const t = setTimeout(() => setInGrace(false), GRACE_MS);
    return () => clearTimeout(t);
  }, [emptyRoute]);
  // The chip is for a picture big enough to carry it: measured where it is drawn, so a 40px cell or a
  // round avatar the classes did not reveal still falls back to the tooltip.
  useEffect(() => {
    const el = holder.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const check = () => {
      const r = el.getBoundingClientRect();
      setChipFits(r.width >= CHIP_MIN_PX && r.height >= CHIP_MIN_PX);
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [src]);
  const slotProps = applyStyleSlot(node.style);
  const callerClass = typeof p.className === "string" ? p.className : undefined;
  const style = { ...resolveStyle(node.style), ...slotProps.style };

  if (!isUsableSrc(src) || failed === src) {
    // An icon / vector with no exported asset stays empty (the Figma mapper
    // emits them); a PHOTO of something is stood in for.
    if (decorative || p.placeholder === false) return null;
    const role = typeof user?.role === "string" ? (user.role as string) : "";
    const situation: PhotoSituation = situationFor(src, !!failed, inGrace);
    return (
      <PhotoPlaceholder
        label={typeof alt === "string" ? alt : undefined}
        situation={situation}
        canEdit={EDITOR_ROLE.test(role)}
        className={callerClass}
        style={style}
        width={width}
        height={height}
        nodeId={node.id}
      />
    );
  }
  const { url, credit } = splitCredit(src);
  const credited = !!credit && !decorative && p.showCredit !== false;
  const chip = credited && !chipSuppressed(callerClass, width, height);
  const { wrapper: wrapCls, img: imgCls } = chip ? splitClasses(callerClass) : { wrapper: "", img: callerClass ?? "" };
  const img = (
    <img
      data-node-id={node.id}
      src={resolveSrc(url)}
      alt={alt ?? ""}
      title={credit ? `Photo by ${credit.name} on Unsplash` : undefined}
      data-credit-link={credit?.link}
      width={width}
      height={height}
      className={chip ? imgCls || undefined : callerClass}
      style={style}
      data-motion={slotProps["data-motion"]}
      onError={() => setFailed(src)}
    />
  );
  if (!chip) return img;       // no credit, or too small / round for a chip: the tooltip above carries it
  // The licence: the photographer and Unsplash, credited where the photo is shown, linked, small.
  // Always visible (a tooltip does not exist on a phone), over the picture's bottom-left corner. The
  // wrapper carries the image's layout classes so the wrapped image is the same box as the plain one.
  const full = /(?:^|\s)w-full(?:\s|$)/.test(callerClass ?? "") || width === "100%";
  return (
    <span
      ref={holder}
      data-photo-credited=""
      className={wrapCls || undefined}
      style={{ position: "relative", display: full ? "block" : "inline-block", lineHeight: 0, maxWidth: "100%",
               overflow: SHAPE_TOKEN.test(wrapCls) || /rounded/.test(wrapCls) ? "hidden" : undefined }}
    >
      {img}
      {chipFits && (
        <span
          data-photo-credit=""
          style={{
            position: "absolute", left: 4, bottom: 4, maxWidth: "calc(100% - 8px)", boxSizing: "border-box", padding: "1px 5px", borderRadius: 3,
            fontSize: 10, lineHeight: 1.4, background: "rgba(0,0,0,0.55)", color: "#fff", whiteSpace: "nowrap",
            overflow: "hidden", textOverflow: "ellipsis", pointerEvents: "auto",
          }}
        >
          Photo by{" "}
          <a href={credit!.link || "https://unsplash.com/?utm_source=tentoro_forge&utm_medium=referral"}
             target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "underline" }}>
            {credit!.name}
          </a>{" "}
          on{" "}
          <a href="https://unsplash.com/?utm_source=tentoro_forge&utm_medium=referral"
             target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "underline" }}>
            Unsplash
          </a>
        </span>
      )}
    </span>
  );
}
