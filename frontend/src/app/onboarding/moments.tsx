"use client";

/**
 * The two moments in onboarding that are worth designing rather than laying out.
 *
 * THE READ IS NOT A SPINNER. Reading a company's site takes five to twenty
 * seconds — long enough that a button with a spinner in it reads as "stuck",
 * and long enough to be the first thing the product ever does for this person.
 * So it says what it is doing, in the order it is actually doing it: open the
 * homepage, count the colours and type, find the mark, read what they do.
 * Those are the four real stages of `services.brand_discovery.run.discover`,
 * not invented progress — but the timing is a guess, so nothing here claims a
 * percentage or a countdown. It names the work and lets the work finish.
 *
 * THE REVEAL IS THE POINT OF THE WHOLE FEATURE. Everything before it is a
 * text field. This is the moment the product hands somebody their own brand
 * back, so the palette draws in and the mark lands, once, and then it is
 * still. Motion that answers what just happened, not decoration on a loop.
 */

import { useEffect, useState } from "react";
import { BrandDesign, COLOR_ROLES } from "@/lib/brand";

/**
 * The stages, in the order `discover()` performs them.
 *
 * Advanced on a timer because the backend is a single POST with no progress
 * to report. That is a real limit and the copy respects it: each line says
 * what is happening, none of them claims to be finished, and the last one
 * holds until the response lands however long that takes.
 */
const STAGES = [
  "Opening your homepage",
  "Reading your colours and type",
  "Looking for your mark",
  "Reading what you do",
];

// A typical read lands in about five seconds, so the four stages have to
// fit inside that to be worth naming. Slower than the work is a sequence
// nobody sees the end of; faster would be theatre.
const STAGE_MS = 1400;

export function ReadingSequence({ host }: { host: string }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)),
      STAGE_MS,
    );
    return () => clearInterval(id);
  }, []);

  return (
    <div className="mt-10 max-w-xl">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Reading{" "}
        <span className="font-medium text-slate-900 dark:text-white">{host}</span>
      </p>
      <ol className="mt-5 space-y-3">
        {STAGES.map((text, i) => {
          const done = i < stage;
          const here = i === stage;
          return (
            <li
              key={text}
              className={[
                "flex items-center gap-3 text-sm transition-opacity duration-500",
                here || done ? "opacity-100" : "opacity-35",
              ].join(" ")}
            >
              <span
                aria-hidden
                className={[
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  done
                    ? "bg-[var(--ob-accent)]"
                    : here
                      ? "bg-[var(--ob-accent)] motion-safe:animate-pulse"
                      : "bg-slate-300 dark:bg-slate-700",
                ].join(" ")}
              />
              <span
                className={
                  here
                    ? "text-slate-900 dark:text-white"
                    : "text-slate-500 dark:text-slate-400"
                }
              >
                {text}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The palette, drawn in once.
 *
 * Swatches rather than a string of hex codes joined by dots: the colours are
 * the evidence, and a person checks them by looking, not by reading six
 * values. The stagger is the only orchestrated motion in the flow and it runs
 * on arrival, never again.
 */
export function PaletteStrip({
  design,
  animate = false,
}: {
  design: BrandDesign;
  animate?: boolean;
}) {
  const swatches = COLOR_ROLES.map((r) => ({
    ...r,
    value: design.colors?.[r.key],
  })).filter((s) => s.value);

  if (swatches.length === 0) return null;

  // NO LABELS. Every one of these roles is named again, with its hex, in the
  // editable fields a few lines below — so a label here is the same word
  // twice on one screen. Stripped, they stop being a legend and read as what
  // they are: the palette. The name still reaches anyone who cannot see the
  // colour, through the accessible text.
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {swatches.map((s, i) => (
        <span
          key={s.key}
          title={`${s.label} ${s.value}`}
          className={[
            "h-7 w-7 rounded-full ring-1 ring-inset ring-black/10",
            animate
              ? "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-50"
              : "",
          ].join(" ")}
          style={{
            background: s.value,
            ...(animate
              ? { animationDelay: `${i * 70}ms`, animationFillMode: "backwards" }
              : {}),
          }}
        >
          <span className="sr-only">{`${s.label}: ${s.value}`}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * The company's name, set in the company's own face.
 *
 * The strongest possible evidence that the typeface was read correctly is to
 * show it doing its job. The family is requested from Google Fonts — the same
 * source the generated application's own token projection uses, so a face
 * that reaches an app reaches this specimen too — and a family that is not
 * there simply falls back, which is also the truth about what the app would
 * do with it.
 */
export function TypeSpecimen({
  name,
  family,
}: {
  name: string;
  family?: string;
}) {
  const clean = (family || "").trim();
  const usable =
    clean &&
    !/^(sans-serif|serif|monospace|system-ui|-apple-system|ui-sans-serif)$/i.test(
      clean,
    );

  useEffect(() => {
    if (!usable) return;
    const href = `https://fonts.googleapis.com/css2?family=${clean.replace(
      / /g,
      "+",
    )}:wght@400;600&display=swap`;
    if (document.querySelector(`link[href="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }, [clean, usable]);

  if (!name) return null;

  return (
    <p
      className="text-3xl leading-tight tracking-tight text-slate-900 dark:text-white"
      style={usable ? { fontFamily: `"${clean}", ui-sans-serif, system-ui` } : undefined}
    >
      {name}
      {usable && (
        <span className="ml-3 align-middle text-xs font-normal tracking-normal text-slate-400">
          {clean}
        </span>
      )}
    </p>
  );
}
