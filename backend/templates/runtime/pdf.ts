/**
 * PDF document builder — pure-JS (pdf-lib), works in Node + serverless (no
 * headless browser). Renders a title, key/value fields (invoices, certificates,
 * record sheets) and/or a table (reports), paginating to A4. Forge runtime.
 */
import { PDFDocument, StandardFonts, rgb } from "pdf-lib";

export interface PdfSpec {
  title?: string;
  subtitle?: string;
  fields?: { label: string; value: unknown }[];
  table?: { columns: string[]; rows: unknown[][] };
  footer?: string;
}

const A4: [number, number] = [595.28, 841.89];
const M = 48; // margin

export async function buildPdf(spec: PdfSpec): Promise<Uint8Array> {
  const doc = await PDFDocument.create();
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const bold = await doc.embedFont(StandardFonts.HelveticaBold);
  const ink = rgb(0.09, 0.11, 0.14);
  const grey = rgb(0.42, 0.46, 0.51);
  const line = rgb(0.85, 0.87, 0.9);
  const W = A4[0];

  let page = doc.addPage(A4);
  let y = A4[1] - M;
  const newPage = () => { page = doc.addPage(A4); y = A4[1] - M; };
  const need = (h: number) => { if (y - h < M) newPage(); };

  const str = (v: unknown) => (v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
  const trunc = (s: string, f: typeof font, size: number, maxW: number) => {
    if (f.widthOfTextAtSize(s, size) <= maxW) return s;
    let t = s;
    while (t.length > 1 && f.widthOfTextAtSize(t + "…", size) > maxW) t = t.slice(0, -1);
    return t + "…";
  };

  if (spec.title) {
    need(28);
    page.drawText(trunc(spec.title, bold, 18, W - 2 * M), { x: M, y: y - 18, size: 18, font: bold, color: ink });
    y -= 26;
  }
  if (spec.subtitle) {
    need(16);
    page.drawText(trunc(spec.subtitle, font, 10, W - 2 * M), { x: M, y: y - 10, size: 10, font, color: grey });
    y -= 20;
  }
  need(12);
  page.drawLine({ start: { x: M, y }, end: { x: W - M, y }, thickness: 1, color: line });
  y -= 16;

  if (spec.fields?.length) {
    for (const f of spec.fields) {
      need(16);
      page.drawText(trunc(String(f.label) + ":", bold, 10, 160), { x: M, y: y - 10, size: 10, font: bold, color: ink });
      page.drawText(trunc(str(f.value), font, 10, W - 2 * M - 170), { x: M + 170, y: y - 10, size: 10, font, color: ink });
      y -= 16;
    }
    y -= 8;
  }

  if (spec.table?.columns?.length) {
    const cols = spec.table.columns;
    const colW = (W - 2 * M) / cols.length;
    const drawHead = () => {
      need(20);
      cols.forEach((c, i) => page.drawText(trunc(String(c), bold, 9, colW - 6), { x: M + i * colW, y: y - 10, size: 9, font: bold, color: ink }));
      y -= 14;
      page.drawLine({ start: { x: M, y }, end: { x: W - M, y }, thickness: 0.75, color: line });
      y -= 10;
    };
    drawHead();
    for (const row of spec.table.rows || []) {
      if (y - 14 < M) { newPage(); drawHead(); }
      cols.forEach((_, i) => page.drawText(trunc(str(row[i]), font, 9, colW - 6), { x: M + i * colW, y: y - 9, size: 9, font, color: ink }));
      y -= 14;
    }
  }

  if (spec.footer) {
    page.drawText(trunc(spec.footer, font, 8, W - 2 * M), { x: M, y: 24, size: 8, font, color: grey });
  }

  return doc.save();
}
