"use client";

interface DiffViewerProps {
  shortId: string;
  pagePath: string;
  iterFrom: number | string;
  iterTo: number | string;
  patchSummary?: string[];
}

export function IterationDiffViewer({
  shortId, pagePath, iterFrom, iterTo, patchSummary,
}: DiffViewerProps) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  const safePage = pagePath.replace(/\//g, "_");
  const fromUrl = `${apiBase}/api/_debug/project-file/${shortId}/.fidelity-history/${safePage}/iter-${iterFrom}.png`;
  const toUrl   = `${apiBase}/api/_debug/project-file/${shortId}/.fidelity-history/${safePage}/iter-${iterTo}.png`;

  return (
    <div className="rounded border bg-card p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
        Iter {iterFrom} → Iter {iterTo}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <figure>
          <figcaption className="text-[10px] uppercase text-muted-foreground mb-1">Before</figcaption>
          <img src={fromUrl} alt={`iter ${iterFrom}`} className="w-full rounded border" />
        </figure>
        <figure>
          <figcaption className="text-[10px] uppercase text-muted-foreground mb-1">After</figcaption>
          <img src={toUrl} alt={`iter ${iterTo}`} className="w-full rounded border" />
        </figure>
      </div>
      {patchSummary && patchSummary.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {patchSummary.map((s, i) => (<li key={i}>↳ {s}</li>))}
        </ul>
      )}
    </div>
  );
}
