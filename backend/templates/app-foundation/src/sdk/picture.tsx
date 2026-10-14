"use client";
/**
 * A stored picture, or a designed stand-in when the field is empty.
 *
 * Image fields are seeded empty on purpose — a made-up file id is a broken
 * picture — and a page that wrote <img src={fileUrl(row.photo)}> showed a
 * bare image box with its alt text on every product and category of a
 * marketplace (Ecom L1, 2026-10-11). The stand-in keeps the layout the
 * picture would have, carries the app's own surface colours and the
 * record's initial, and gives way to the picture the moment one is
 * uploaded. A picture that fails to load falls back the same way.
 */
import * as React from "react";
import { fileUrl } from "./files";

type Props = Omit<React.ImgHTMLAttributes<HTMLImageElement>, "src" | "alt"> & {
  /** The image field's value: a stored file's id, a URL, or empty. */
  src: string | null | undefined;
  /** What the picture is of — read out, and the stand-in's initial. */
  alt: string;
  /** Shown in the stand-in instead of the first letter of `alt`. */
  mark?: React.ReactNode;
};

export function Picture({ src, alt, className, mark, style, ...rest }: Props) {
  const [failed, setFailed] = React.useState(false);
  const url = fileUrl(src);
  if (!url || failed) {
    const initial = (alt || "").trim().charAt(0).toUpperCase();
    return (
      <div
        role="img"
        aria-label={alt}
        className={["flex items-center justify-center overflow-hidden bg-muted text-muted-foreground", className ?? ""].join(" ")}
        style={{
          backgroundImage: "linear-gradient(135deg, hsl(var(--muted)) 0%, hsl(var(--accent, var(--muted))) 100%)",
          ...style,
        }}
      >
        <span className="font-heading text-3xl opacity-60 select-none" aria-hidden="true">{mark ?? initial}</span>
      </div>
    );
  }
  return <img src={url} alt={alt} className={className} style={style} onError={() => setFailed(true)} {...rest} />;
}
