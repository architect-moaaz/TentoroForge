"use client";
import * as React from "react";
import { useState } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { LightboxPropsType } from "./Lightbox.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface LightboxProps extends LightboxPropsType {
  style?: StyleSlotT;
}

export function Lightbox({ images = [], className, style }: LightboxProps) {
  const [open, setOpen] = useState<number | null>(null);

  const total = images.length;

  function prev() {
    setOpen((i) => (i === null ? null : (i - 1 + total) % total));
  }

  function next() {
    setOpen((i) => (i === null ? null : (i + 1) % total));
  }

  function close() {
    setOpen(null);
  }

  const current = open !== null ? images[open] : null;

  return (
    <div
      data-lightbox=""
      className={className}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {/* Thumbnail grid */}
      <div className="flex flex-wrap gap-2">
        {images.map((img, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Open ${img.alt ?? `image ${i + 1}`}`}
            onClick={() => setOpen(i)}
            className="cursor-pointer overflow-hidden rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <img
              src={img.src}
              alt={img.alt ?? `image ${i + 1}`}
              className="h-24 w-24 object-cover"
            />
          </button>
        ))}
      </div>

      {/* Overlay */}
      {open !== null && current && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={close}
        >
          {/* Inner panel — stop propagation so clicking image/buttons doesn't close */}
          <div
            className="relative flex flex-col items-center gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={current.src}
              alt={current.alt ?? `image ${open + 1}`}
              className="max-h-[80vh] max-w-[90vw] object-contain"
            />
            <div className="flex items-center gap-4">
              <button
                type="button"
                aria-label="Previous"
                onClick={prev}
                className="rounded bg-white/20 px-3 py-1 text-white hover:bg-white/40"
              >
                &#8592; Previous
              </button>
              <button
                type="button"
                aria-label="Next"
                onClick={next}
                className="rounded bg-white/20 px-3 py-1 text-white hover:bg-white/40"
              >
                Next &#8594;
              </button>
              <button
                type="button"
                aria-label="Close"
                onClick={close}
                className="rounded bg-white/20 px-3 py-1 text-white hover:bg-white/40"
              >
                &#10005; Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
