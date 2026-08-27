/**
 * GET /api/search?q=<query>
 *
 * SearchInput (from @tentoroforge/library) hits this and expects a
 * `SearchHit[]` back:
 *   { id, entity, snippet: "<b>match</b>…", rank, <primaryField> }
 *
 * Full-text search over the Document.ocrText column PLUS every value
 * inside Document.extractedFields (jsonb). Uses ILIKE for portability
 * (no tsvector column required); ranks by count of case-insensitive
 * matches; builds a <b>-highlighted snippet around the first hit.
 *
 * Multi-word queries are OR'd — any word matching is a hit; ranking
 * favours documents matching more words. Trimmed queries under 2
 * chars return [].
 */

import { NextResponse } from "next/server";
import { db } from "@/db";
import { documents } from "@/db/schema";
import { sql, or, ilike, desc } from "drizzle-orm";

const ESCAPE_HTML: Record<string, string> = {
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
};
function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESCAPE_HTML[c]);
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function buildSnippet(text: string, terms: string[], length = 160): string {
  if (!text) return "";
  // Find the earliest match position across all terms.
  let firstHit = -1;
  for (const t of terms) {
    if (!t) continue;
    const idx = text.toLowerCase().indexOf(t.toLowerCase());
    if (idx !== -1 && (firstHit === -1 || idx < firstHit)) firstHit = idx;
  }
  const center = firstHit === -1 ? 0 : firstHit;
  const halfWindow = Math.floor(length / 2);
  const start = Math.max(0, center - halfWindow);
  const end = Math.min(text.length, start + length);
  const clip = text.slice(start, end);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < text.length ? "…" : "";
  const escaped = escapeHtml(clip);
  // Wrap every term match in <b>…</b>. Apply longest-first so shorter terms
  // don't corrupt already-wrapped spans.
  const sortedTerms = [...terms].filter(Boolean).sort((a, b) => b.length - a.length);
  let highlighted = escaped;
  for (const t of sortedTerms) {
    const re = new RegExp(`(${escapeRegExp(escapeHtml(t))})`, "gi");
    highlighted = highlighted.replace(re, "<b>$1</b>");
  }
  return prefix + highlighted + suffix;
}

function extractedFieldsToText(fields: unknown): string {
  if (!fields || typeof fields !== "object") return "";
  return Object.entries(fields as Record<string, unknown>)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" | ");
}

function countHits(haystack: string, terms: string[]): number {
  if (!haystack) return 0;
  const lc = haystack.toLowerCase();
  let hits = 0;
  for (const t of terms) {
    if (!t) continue;
    const lct = t.toLowerCase();
    let from = 0;
    while (true) {
      const idx = lc.indexOf(lct, from);
      if (idx === -1) break;
      hits++;
      from = idx + lct.length;
    }
  }
  return hits;
}

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") ?? "").trim();
  if (q.length < 2) return NextResponse.json([]);

  // Split on whitespace, keep quoted phrases together.
  const rawTerms = q.match(/"[^"]+"|\S+/g) ?? [];
  const terms = rawTerms.map((t) => t.replace(/^"|"$/g, "")).filter((t) => t.length > 0);
  if (terms.length === 0) return NextResponse.json([]);

  // Pre-filter with ILIKE on ocr_text OR the jsonb cast-to-text — narrows
  // the row set before we do the per-row rank/snippet work in JS.
  const orClauses = terms.flatMap((t) => [
    ilike(documents.ocrText, `%${t}%`),
    sql`${documents.extractedFields}::text ILIKE ${"%" + t + "%"}`,
  ]);

  const rows = await db
    .select({
      id: documents.id,
      originalFilename: documents.originalFilename,
      ocrText: documents.ocrText,
      extractedFields: documents.extractedFields,
      createdAt: documents.createdAt,
    })
    .from(documents)
    .where(or(...orClauses))
    .orderBy(desc(documents.createdAt))
    .limit(50);

  // Rank in-app: total hit count across ocr_text + serialised jsonb.
  // Attach a snippet biased toward ocr_text (visual anchor), falling
  // back to the field-serialisation when OCR is empty.
  const hits = rows
    .map((r) => {
      const fieldsText = extractedFieldsToText(r.extractedFields);
      const source = r.ocrText || fieldsText;
      const rank = countHits(r.ocrText ?? "", terms) + countHits(fieldsText, terms);
      const snippet = buildSnippet(source, terms);
      return {
        id: r.id,
        entity: "documents",
        rank,
        snippet,
        originalFilename: r.originalFilename ?? "(untitled)",
      };
    })
    .filter((h) => h.rank > 0)
    .sort((a, b) => b.rank - a.rank)
    .slice(0, 25);

  return NextResponse.json(hits);
}
