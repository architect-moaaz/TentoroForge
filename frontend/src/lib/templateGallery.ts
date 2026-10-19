"use client";

import { useEffect, useState } from "react";
import { authFetch } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export type TemplateStatus =
  | "draft"
  | "pending"
  | "approved"
  | "rejected"
  | "removed"
  | "superseded";

export interface TemplatePerson {
  id: string;
  name: string;
  avatar_url: string | null;
}

export interface TemplateShot {
  id: string;
  caption: string;
  width: number;
  height: number;
  source: "upload" | "app";
}

export interface TemplateCheck {
  key: string;
  ok: boolean;
  label: string;
  detail: string;
  blocking: boolean;
}

export interface TemplateCardData {
  id: string;
  org_id: string;
  org_name: string;
  name: string;
  description: string;
  category: string;
  version: number;
  status: TemplateStatus;
  creator: TemplatePerson | null;
  created_by_name: string;
  source_project_id: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  published_at: string | null;
  review_note: string;
  pricing: { model: "free" | "paid"; price_cents: number | null; currency: string | null };
  summary: {
    name?: string;
    counts?: Record<string, number>;
    pages?: string[];
    palette?: string[];
    designed?: boolean;
  };
  screenshots: TemplateShot[];
  uses: number;
  rating: number | null;
  ratings: number;
  can_manage: boolean;
  can_use: boolean;
  can_rate: boolean;
  /** The person belongs to the organisation that built it. */
  own_org: boolean;
  editable: boolean;
}

export interface TemplatePreview {
  screens: { name: string; route: string; purpose: string; who: string[] }[];
  records: {
    name: string;
    description: string;
    fields: { name: string; type: string; required: boolean; description: string }[];
  }[];
  workflows: { name: string; purpose: string; trigger: string; steps: string[] }[];
  roles: { name: string; description: string }[];
  rules: { name: string; statement: string; record: string }[];
}

export interface TemplateDetailData extends TemplateCardData {
  preview: TemplatePreview | null;
  checks?: TemplateCheck[];
  history?: { status: TemplateStatus; note: string; by: string; at: string | null }[];
  my_review: { rating: number; comment: string } | null;
  is_admin: boolean;
}

export interface TemplateReviewData {
  id: string;
  user: TemplatePerson;
  rating: number;
  comment: string;
  used_it: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** How each status reads, to the builder and to everyone else. */
export const STATUS_LABEL: Record<TemplateStatus, string> = {
  draft: "Private",
  pending: "In review",
  approved: "In the Gallery",
  rejected: "Changes needed",
  removed: "Taken out",
  superseded: "Older version",
};

export const STATUS_TONE: Record<TemplateStatus, string> = {
  draft: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  removed: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  superseded: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export function shotPath(templateId: string, shotId: string) {
  return `/api/project-templates/${templateId}/screenshots/${shotId}`;
}

/**
 * Pictures already fetched this visit, by path. A screenshot never changes
 * (a new one has a new id), and the same one is drawn on a card, in the
 * detail view and on the builder's profile — fetched once, shown everywhere.
 * Kept small: the oldest are let go past the limit.
 */
const IMAGE_CACHE = new Map<string, Promise<string | null>>();
const IMAGE_CACHE_MAX = 120;

function loadImage(path: string): Promise<string | null> {
  const hit = IMAGE_CACHE.get(path);
  if (hit) return hit;
  const loading = authFetch(`${API_BASE}${path}`)
    .then((r) => (r.ok ? r.blob() : null))
    .then((blob) => (blob ? URL.createObjectURL(blob) : null))
    .catch(() => null)
    .then((url) => {
      // A failure is not remembered: the next view tries again.
      if (!url) IMAGE_CACHE.delete(path);
      return url;
    });
  IMAGE_CACHE.set(path, loading);
  if (IMAGE_CACHE.size > IMAGE_CACHE_MAX) {
    const oldest = IMAGE_CACHE.keys().next().value as string;
    const gone = IMAGE_CACHE.get(oldest);
    IMAGE_CACHE.delete(oldest);
    gone?.then((u) => u && setTimeout(() => URL.revokeObjectURL(u), 60_000));
  }
  return loading;
}

/**
 * A picture behind sign-in. An <img src> cannot carry the bearer token, and a
 * template's screenshots are as private as the template until it is published,
 * so they are fetched as the signed-in person and shown from a blob URL.
 */
export function useAuthedImage(path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setUrl(null);
      return;
    }
    let alive = true;
    loadImage(path).then((u) => alive && setUrl(u));
    return () => {
      alive = false;
    };
  }, [path]);
  return url;
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function initials(name: string | undefined | null) {
  const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export const COUNTED: [string, string, string][] = [
  ["pages", "screen", "screens"],
  ["entities", "data model", "data models"],
  ["workflows", "workflow", "workflows"],
  ["roles", "role", "roles"],
];

export function countsLine(counts: Record<string, number> | undefined) {
  return COUNTED.filter(([k]) => counts?.[k])
    .map(([k, one, many]) => `${counts![k]} ${counts![k] === 1 ? one : many}`)
    .join(" · ");
}
