"use client";
/**
 * ImageControl — set an image prop by dropping a file, browsing for one, or
 * typing a URL.
 *
 * Three things this control has to get right and one it cannot:
 *
 * 1. The URL it writes must resolve in BOTH surfaces. It never invents one —
 *    it stores whatever `POST /api/projects/<id>/images` returns, which is
 *    `/api/asset/<short_id>/figma/<file>`, a path both the editor (:6501) and
 *    the render-scaffold (:6503) serve from their own copies of the same route
 *    handler. See backend/services/project_assets.py for why the bytes are
 *    written to two directories to make that true.
 *
 * 2. Typing a URL must keep working. Plenty of images are already on a CDN and
 *    a user who pastes one should not be pushed through an upload. The text
 *    field is the same control as before, not a fallback.
 *
 * 3. Every refusal is visible. A silently ignored drop is indistinguishable
 *    from a broken editor, so wrong-type / too-big / network-failed all land in
 *    the same error line with the server's own wording where there is one.
 *
 * What it cannot do: tell the user the slot's size for a component whose CSS
 * does not pin one. `slotSizeFor` answers in pixels for Avatar and PersonCard
 * (their classes fix a square) and says "fluid" for Hero, rather than inventing
 * a recommended width this codebase has no basis for.
 */
import * as React from "react";
import { api, ApiError } from "@/lib/api";
import {
  IMAGE_ACCEPT_ATTR,
  describeFit,
  formatBytes,
  readImageDimensions,
  readImageUrl,
  slotSizeFor,
  validateImageFile,
  writeImageUrl,
  type ImageShape,
  type PixelSize,
} from "@/lib/image-asset";

const labelText = "text-xs uppercase tracking-wide text-muted-foreground";

export interface ImageControlProps {
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
  /** Shape the prop stores its URL in — from the registry descriptor. */
  imageShape?: ImageShape;
  /** Owning node's type + props, for the slot-size hint. */
  nodeType?: string;
  nodeProps?: Record<string, unknown>;
  /** Project SHORT id; uploads are disabled without it. */
  projectId?: string | null;
}

interface UploadResponse {
  url: string;
  file: string;
  media_type: string;
  bytes: number;
}

export function ImageControl({
  label,
  value,
  onChange,
  imageShape = "url",
  nodeType,
  nodeProps,
  projectId,
}: ImageControlProps) {
  const url = readImageUrl(value, imageShape);

  const [dragging, setDragging] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [dims, setDims] = React.useState<PixelSize | null>(null);
  const [dimsError, setDimsError] = React.useState<string | null>(null);
  const [uploadedBytes, setUploadedBytes] = React.useState<number | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const slot = slotSizeFor(nodeType, label, nodeProps);

  // Measure whatever URL the prop currently holds, however it got there —
  // uploaded, typed, or already in the schema when the node was selected. This
  // is why dimensions are read in the browser instead of returned by the
  // upload endpoint: the typed-URL and pre-existing-value cases have no upload
  // to report them.
  React.useEffect(() => {
    let cancelled = false;
    setDims(null);
    setDimsError(null);
    if (!url) return;
    readImageDimensions(url).then(
      (d) => { if (!cancelled) setDims(d); },
      (e: Error) => { if (!cancelled) setDimsError(e.message); },
    );
    return () => { cancelled = true; };
  }, [url]);

  const commit = React.useCallback(
    (nextUrl: string) => onChange(writeImageUrl(value, imageShape, nextUrl)),
    [onChange, value, imageShape],
  );

  // The URL box is edited locally and committed on blur / Enter. Wiring it
  // straight to `commit` dispatched one updateProp PER KEYSTROKE, and
  // editor-store pushes one undo entry per dispatch and re-arms the 500 ms
  // autosave on each — so pasting-then-editing a 60-character URL buried the
  // previous value 60 Ctrl-Zs deep and fired a save storm. Same commit-on-blur
  // contract as SizeField in StylePanel.tsx. `url` is derived from the prop, so
  // the effect re-syncs whenever an upload or an external edit changes it.
  const [urlDraft, setUrlDraft] = React.useState(url);
  React.useEffect(() => { setUrlDraft(url); }, [url]);
  const commitUrlDraft = () => {
    if (urlDraft === url) return;
    setUploadedBytes(null);
    setError(null);
    commit(urlDraft);
  };

  async function acceptFile(file: File) {
    setError(null);
    const verdict = validateImageFile({ name: file.name, type: file.type, size: file.size });
    if (!verdict.ok) {
      setError(verdict.message);
      return;
    }
    if (!projectId) {
      setError("No project is open, so there is nowhere to upload to. Paste a URL instead.");
      return;
    }

    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const rec = await api.upload<UploadResponse>(`/api/projects/${projectId}/images`, form);
      setUploadedBytes(rec.bytes);
      commit(rec.url);
    } catch (e) {
      // The backend's 400 wording ("… is not an image", "… is too large") is
      // written to be read by a human, so show it rather than a generic
      // "upload failed" that hides which rule was broken.
      setError(
        e instanceof ApiError
          ? e.message
          : `Couldn't upload ${file.name} — ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const file = e.dataTransfer?.files?.[0];
    if (!file) {
      // A drag carrying no file is usually a dragged <img> from another page,
      // which arrives as a text/uri-list instead. Take it as a typed URL.
      const uri = e.dataTransfer?.getData("text/uri-list") || e.dataTransfer?.getData("text/plain");
      if (uri) { setError(null); commit(uri.trim()); return; }
      setError("That drop carried no file.");
      return;
    }
    void acceptFile(file);
  }

  const dimsLine = dims
    ? `${dims.width} x ${dims.height} px${uploadedBytes != null ? ` · ${formatBytes(uploadedBytes)}` : ""}`
    : url && dimsError
      ? dimsError
      : url
        ? "measuring…"
        : null;

  const fitLine = describeFit(dims, slot);

  return (
    <div className="flex flex-col gap-1 text-sm">
      <span className={labelText}>{label}</span>

      <div
        // The drop target is a div, not a label wrapping the input: a <label>
        // would swallow the click on the "Remove" button inside it and open the
        // file picker instead.
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setDragging(false); }}
        onDrop={onDrop}
        onClick={() => { if (!busy) fileInputRef.current?.click(); }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); }
        }}
        role="button"
        tabIndex={0}
        aria-label={`${label}: drop an image or click to browse`}
        aria-busy={busy}
        data-testid="image-dropzone"
        className={[
          "relative flex items-center gap-2 rounded border border-dashed p-2 cursor-pointer transition-colors",
          dragging ? "border-primary bg-primary/10" : "border-muted-foreground/40 bg-background",
          busy ? "opacity-60 pointer-events-none" : "",
        ].join(" ")}
      >
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt=""
            className="h-12 w-12 shrink-0 rounded object-cover bg-muted"
            // A thumbnail that fails to load is itself the message that the URL
            // is wrong; the dimension reader reports the same failure in words.
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
          />
        ) : (
          <div className="h-12 w-12 shrink-0 rounded bg-muted" aria-hidden />
        )}
        <div className="min-w-0 flex-1 text-xs leading-tight">
          <div className="text-muted-foreground">
            {busy ? "Uploading…" : url ? "Drop a new image, or click to browse" : "Drop an image here, or click to browse"}
          </div>
          {dimsLine && <div className="mt-0.5 font-medium text-foreground">{dimsLine}</div>}
        </div>
        {url && (
          <button
            type="button"
            className="shrink-0 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
            onClick={(e) => { e.stopPropagation(); setUploadedBytes(null); setError(null); commit(""); }}
          >
            Remove
          </button>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept={IMAGE_ACCEPT_ATTR}
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            // Reset the input's value so re-picking the SAME file after a
            // failed upload fires change again (it would not otherwise).
            e.target.value = "";
            if (f) void acceptFile(f);
          }}
        />
      </div>

      {fitLine && <p className="text-[11px] text-muted-foreground">{fitLine}</p>}
      {!fitLine && slot && <p className="text-[11px] text-muted-foreground">Slot {slot.note}.</p>}

      {error && (
        <p role="alert" className="text-[11px] text-destructive">{error}</p>
      )}

      <input
        type="text"
        aria-label={`${label} URL`}
        className="border rounded px-2 py-1 text-xs bg-background font-mono"
        placeholder="…or paste an image URL"
        value={urlDraft}
        onChange={(e) => setUrlDraft(e.target.value)}
        onBlur={commitUrlDraft}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          else if (e.key === "Escape") {
            setUrlDraft(url);
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
    </div>
  );
}
