"use client";

// A Figma frame is a fixed-size drawing, so it is SCALED to the space it gets
// rather than cropped by it.
//
// A frame is authored at one size — 3902x1975 on a real dashboard — and every
// node inside it is positioned in those coordinates. Rendered into a
// viewport-width column the design is not wrong, it is simply off-screen to
// the right: the header and the first three cards show and the other twenty-odd
// sit past the edge. Scaling the whole canvas by (available width / frame
// width) puts all of it on screen at the proportions it was drawn in.
//
// MEASURED, NOT ASSUMED. The width comes from this wrapper's own box, so the
// result is right inside the dashboard shell, inside the `_figmaDerived`
// full-bleed escape, and on a phone, without any of those having to agree
// about a number in advance.
//
// A client component because `schema-page.tsx` is a server one — it resolves
// dataSources server-side for correct SSR — and this needs layout measurement.

import * as React from "react";

export function FigmaCanvas({
  width,
  height,
  fit = "scale",
  children,
}: {
  width: number;
  height: number;
  /** `fluid`: the frame reflows below its width (auto-layout frames);
   *  `scale`: it shrinks as a picture (positioned frames). */
  fit?: "scale" | "fluid";
  children: React.ReactNode;
}) {
  if (fit === "fluid") {
    // A drawn box is a maximum, not a size: the page is at most the frame's
    // width and its containers reflow inside that. No transform, no fixed
    // height — the content is as tall as it needs to be at this width.
    return (
      <div className="w-full" style={{ maxWidth: width }}>
        {children}
      </div>
    );
  }
  return <ScaledCanvas width={width} height={height}>{children}</ScaledCanvas>;
}

function ScaledCanvas({
  width,
  height,
  children,
}: {
  width: number;
  height: number;
  children: React.ReactNode;
}) {
  const hostRef = React.useRef<HTMLDivElement | null>(null);
  // 1 until measured: a first paint at natural size shows the top-left corner
  // of the design, which is the least-wrong thing to show for one frame.
  const [scale, setScale] = React.useState(1);

  React.useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host || !width) return;
    const measure = () => {
      const avail = host.clientWidth;
      // Never scale UP. A frame narrower than the viewport is shown at the size
      // it was drawn, because enlarging a raster export blurs it.
      if (avail > 0) setScale(Math.min(1, avail / width));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    return () => ro.disconnect();
  }, [width]);

  return (
    <div ref={hostRef} className="w-full overflow-hidden">
      <div
        style={{
          width,
          height,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          // A transform does not affect layout, so the canvas keeps its
          // UNSCALED height in flow and the page would carry ~1975px of dead
          // space beneath a scaled-down frame. Pulling the difference back
          // closes the gap without a second measurement.
          marginBottom: height * (scale - 1),
        }}
      >
        {children}
      </div>
    </div>
  );
}
