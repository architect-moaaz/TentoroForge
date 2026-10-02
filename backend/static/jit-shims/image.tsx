// next/image for the editor's JIT preview: a plain <img>.
import * as React from "react";
type Props = React.ImgHTMLAttributes<HTMLImageElement> & { src: string | { src: string }; fill?: boolean; priority?: boolean; quality?: number; unoptimized?: boolean; placeholder?: string; blurDataURL?: string; loader?: unknown; sizes?: string };
export default function Image({ src, fill, priority, quality, unoptimized, placeholder, blurDataURL, loader, style, ...rest }: Props) {
  const s = typeof src === "string" ? src : src.src;
  return <img src={s} style={fill ? { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", ...style } : style} {...rest} />;
}
