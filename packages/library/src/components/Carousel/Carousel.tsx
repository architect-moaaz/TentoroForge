"use client";
import * as React from "react";
import { useState } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CarouselPropsType } from "./Carousel.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CarouselComponentProps extends CarouselPropsType {
  style?: StyleSlotT;
}

export function Carousel({ items = [], className, style }: CarouselComponentProps) {
  const [index, setIndex] = useState(0);

  if (items.length === 0) {
    return (
      <div data-carousel="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
        <div data-testid="carousel-active" />
      </div>
    );
  }

  const n = items.length;
  const active = items[index];

  function goNext() {
    setIndex((index + 1) % n);
  }

  function goPrev() {
    setIndex((index - 1 + n) % n);
  }

  return (
    <div
      data-carousel=""
      className={className}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {/* Slide track */}
      <div data-testid="carousel-active">
        {active.image && (
          <img src={active.image} alt={active.title ?? ""} />
        )}
        {active.title && <p>{active.title}</p>}
        {active.caption && <p>{active.caption}</p>}
      </div>

      {/* Controls */}
      <button type="button" aria-label="Previous slide" onClick={goPrev}>
        ‹
      </button>
      <button type="button" aria-label="Next slide" onClick={goNext}>
        ›
      </button>

      {/* Dot navigation */}
      <div>
        {items.map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Go to slide ${i + 1}`}
            aria-current={i === index ? "true" : undefined}
            onClick={() => setIndex(i)}
          />
        ))}
      </div>
    </div>
  );
}
