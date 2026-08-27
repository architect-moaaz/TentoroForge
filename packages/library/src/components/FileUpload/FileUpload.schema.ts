import { z } from "zod";

/**
 * FileUpload — Spec E Wave 3 resumable/retry additions.
 *
 * `resumable` opts into a chunked upload contract (planned S3/tus
 * bridge; the current runtime falls back to a single-shot POST when
 * the bridge isn't wired). `retryOn5xx` turns on exponential-backoff
 * retry on transient server errors.
 */
export const FileUploadProps = z.object({
  name:      z.string().default("file"),
  label:     z.string().optional(),
  accept:    z.string().optional(),
  multiple:  z.boolean().optional(),
  maxSizeMb: z.number().optional(),
  hint:      z.string().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),

  // Companion hidden-input names. The generated entity's columns don't
  // always spell these the conventional way (`fileMimeType` vs
  // `mimeType`), and the workflow insert binds by exact name — these
  // let the generator align the hidden inputs to the real columns.
  filenameField: z.string().optional(),
  mimeTypeField: z.string().optional(),

  // ── Spec E Wave 3 additions ──
  resumable:  z.boolean().optional(),
  retryOn5xx: z.boolean().optional(),
  chunkSizeMb: z.number().int().min(1).max(50).optional(),
});
export type FileUploadPropsType = z.infer<typeof FileUploadProps>;
