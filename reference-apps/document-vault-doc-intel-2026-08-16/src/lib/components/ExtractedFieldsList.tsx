"use client";

import * as React from "react";
import { z } from "zod";

/**
 * ExtractedFieldsList — dynamic key/value display for a jsonb map.
 *
 * The library's built-in `DescriptionList` takes a static `items: [{term,
 * description}]` array — no way to bind a jsonb column whose keys are
 * discovered at runtime (an AI extraction pass). This component takes the
 * whole map, sorts keys alphabetically, humanises the labels, and renders
 * one row per entry.
 *
 * Optional `confidenceMap` overlays a per-field confidence chip when the
 * workflow emits a parallel object of `{fieldName: 0-1}` scores.
 */
export const ExtractedFieldsListProps = z
  .object({
    data: z.record(z.unknown()).optional(),
    confidenceMap: z.record(z.number()).optional(),
    emptyText: z.string().default("No fields extracted yet."),
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
  })
  .strict();

export type ExtractedFieldsListPropsT = z.infer<typeof ExtractedFieldsListProps>;

function humanize(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function stringify(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

function confidenceTone(score: number): { bg: string; fg: string; label: string } {
  if (score >= 0.85) return { bg: "hsl(142 40% 92%)", fg: "hsl(142 60% 25%)", label: "high" };
  if (score >= 0.6)  return { bg: "hsl(45 90% 92%)",  fg: "hsl(30 65% 30%)",  label: "med"  };
  return { bg: "hsl(0 60% 94%)", fg: "hsl(0 55% 32%)", label: "low" };
}

export function ExtractedFieldsList(props: ExtractedFieldsListPropsT): React.ReactElement {
  const { data, confidenceMap, emptyText, orientation } = props;
  const entries = React.useMemo(() => {
    if (!data || typeof data !== "object") return [];
    return Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  if (entries.length === 0) {
    return (
      <div style={{ color: "hsl(220 8% 45%)", fontStyle: "italic", padding: "0.5rem 0" }}>
        {emptyText}
      </div>
    );
  }

  const horizontal = orientation === "horizontal";

  return (
    <dl
      style={{
        display: "grid",
        gridTemplateColumns: horizontal ? "minmax(140px, max-content) 1fr" : "1fr",
        rowGap: "0.5rem",
        columnGap: "1rem",
        margin: 0,
      }}
    >
      {entries.map(([k, v]) => {
        const score = confidenceMap?.[k];
        const chip = typeof score === "number" ? confidenceTone(score) : null;
        return (
          <React.Fragment key={k}>
            <dt style={{
              fontSize: "0.8125rem",
              fontWeight: 500,
              color: "hsl(220 8% 40%)",
              margin: 0,
            }}>
              {humanize(k)}
            </dt>
            <dd style={{
              margin: 0,
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              fontFamily: "IBM Plex Mono, ui-monospace, monospace",
              fontSize: "0.875rem",
              color: "hsl(220 15% 15%)",
              wordBreak: "break-word",
            }}>
              <span>{stringify(v)}</span>
              {chip && (
                <span style={{
                  fontSize: "0.6875rem",
                  fontWeight: 600,
                  padding: "0.125rem 0.375rem",
                  borderRadius: "9999px",
                  background: chip.bg,
                  color: chip.fg,
                  letterSpacing: "0.02em",
                  textTransform: "uppercase",
                }}>
                  {chip.label} · {Math.round(score! * 100)}%
                </span>
              )}
            </dd>
          </React.Fragment>
        );
      })}
    </dl>
  );
}
