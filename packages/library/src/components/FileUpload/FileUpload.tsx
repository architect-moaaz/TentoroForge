"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { FileUploadPropsType } from "./FileUpload.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface FileUploadRef {
  id: string;
  url: string;
  filename: string;
  contentType: string;
  size: number;
}

export interface FileUploadProps extends FileUploadPropsType {
  style?: StyleSlotT;
  onFiles?: (files: File[]) => void;
  onUploaded?: (refs: FileUploadRef[]) => void;
  /** Endpoint that stores the file and returns a FileUploadRef. */
  uploadUrl?: string;
}

type Item = { file: File; status: "uploading" | "done" | "error"; ref?: FileUploadRef };

/**
 * Uploads selected files to the app's storage endpoint and carries the resulting
 * file id(s) in a hidden input under `name`, so a container-mode Form submits them
 * (single → the id string; multiple → a JSON array of ids). The id maps cleanly to
 * a uuid column and is resolvable by an ai_extract node's `aiFileRef`.
 */
export function FileUpload({
  name, label, accept, multiple, maxSizeMb, hint, style,
  filenameField = "originalFilename", mimeTypeField = "mimeType",
  onFiles, onUploaded, uploadUrl = "/api/files/upload",
}: FileUploadProps) {
  const [dragOver, setDragOver] = React.useState(false);
  const [items, setItems] = React.useState<Item[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const uploadOne = async (file: File): Promise<FileUploadRef | null> => {
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(uploadUrl, { method: "POST", body: fd });
      if (!res.ok) return null;
      return (await res.json()) as FileUploadRef;
    } catch {
      return null;
    }
  };

  const acceptFiles = async (list: FileList | null) => {
    if (!list) return;
    const arr = Array.from(list).filter((f) => maxSizeMb === undefined || f.size <= maxSizeMb * 1024 * 1024);
    if (!arr.length) return;
    onFiles?.(arr);
    const fresh: Item[] = arr.map((file) => ({ file, status: "uploading" }));
    setItems((prev) => (multiple ? [...prev, ...fresh] : fresh));
    const settled: Item[] = [];
    for (const it of fresh) {
      const ref = await uploadOne(it.file);
      settled.push({ ...it, status: ref ? "done" : "error", ref: ref ?? undefined });
    }
    setItems((prev) => {
      const next = multiple ? prev.map((p) => settled.find((s) => s.file === p.file) ?? p) : settled;
      onUploaded?.(next.filter((n) => n.ref).map((n) => n.ref as FileUploadRef));
      return next;
    });
  };

  const ids = items.filter((i) => i.ref).map((i) => (i.ref as FileUploadRef).id);
  const value = multiple ? JSON.stringify(ids) : ids[0] ?? "";
  // "Nothing uploaded yet" — in multi mode `value` is "[]", not "".
  const hasValue = ids.length > 0;
  const busy = items.some((i) => i.status === "uploading");
  // Companion hidden inputs so a container-mode Form submits filename + mimeType
  // alongside `name` (the id). Convention: consumers expect `originalFilename` and
  // `mimeType` keys — this lets a `documents` INSERT bind them without a separate
  // db_select round-trip. Suppressed in multi mode (they only make sense for one file).
  const firstRef = items.find((i) => i.ref)?.ref;
  const originalFilename = firstRef?.filename ?? items[0]?.file?.name ?? "";
  const mimeType = firstRef?.contentType ?? items[0]?.file?.type ?? "";

  return (
    <div className="flex flex-col gap-1" data-file-upload="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      {/* Hidden control carries the uploaded file id(s) for form submission.
        * Rendered ONLY once a file is uploaded: FormData keeps the LAST value
        * per name, so an always-present empty input here clobbers a sibling
        * control sharing the same field name (e.g. CameraCapture writing
        * `imageUrl`) whenever this component renders after it in the form. */}
      {hasValue && <input type="hidden" name={name} value={value} readOnly />}
      {!multiple && hasValue && (
        <>
          <input type="hidden" name={filenameField} value={originalFilename} readOnly />
          <input type="hidden" name={mimeTypeField} value={mimeType} readOnly />
        </>
      )}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); acceptFiles(e.dataTransfer.files); }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed px-4 py-6 text-center text-sm ${dragOver ? "border-primary bg-primary/5" : "border-input text-muted-foreground"}`}
      >
        <span>{busy ? "Uploading…" : "Drag & drop or click to browse"}</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
        <input
          ref={inputRef} data-testid="file-upload-input" type="file" accept={accept} multiple={multiple}
          className="hidden" onChange={(e) => acceptFiles(e.target.files)} />
      </div>
      {items.length > 0 && (
        <ul className="text-xs text-foreground">
          {items.map((it, i) => (
            <li key={i} className="flex items-center gap-1">
              <span>{it.file.name} ({Math.round(it.file.size / 1024)} KB)</span>
              <span className={it.status === "error" ? "text-destructive" : "text-muted-foreground"}>
                {it.status === "uploading" ? "· uploading…" : it.status === "done" ? "· ✓" : "· failed"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
