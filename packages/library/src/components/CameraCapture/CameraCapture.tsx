"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CameraCapturePropsType } from "./CameraCapture.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CameraCaptureComponentProps extends CameraCapturePropsType {
  style?: StyleSlotT;
  onCapture?: (dataUrl: string) => void;
  /** Endpoint that receives multipart file uploads and returns
   * `{ id, url, mime, filename }` — matches FileUpload's default. */
  uploadUrl?: string;
  /** Called with the platform file-record id after a successful upload. */
  onUploaded?: (fileId: string) => void;
}

export function CameraCapture({
  name,
  label,
  captureLabel,
  style,
  onCapture,
  uploadUrl = "/api/files/upload",
  onUploaded,
}: CameraCaptureComponentProps) {
  const [streaming, setStreaming] = React.useState(false);
  const [photo, setPhoto] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [uploadedId, setUploadedId] = React.useState<string>("");

  const videoRef = React.useRef<HTMLVideoElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const streamRef = React.useRef<MediaStream | null>(null);

  async function startCamera() {
    setError(null);
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Camera not supported in this browser.");
        return;
      }
      // Rear lens first — scanning a product with the selfie camera is a
      // dead end; fall back to any camera (laptops, single-lens devices).
      const stream = await navigator.mediaDevices
        .getUserMedia({ video: { facingMode: { ideal: "environment" } } })
        .catch(() => navigator.mediaDevices.getUserMedia({ video: true }));
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        if (typeof videoRef.current.play === "function") {
          await videoRef.current.play();
        }
      }
      setStreaming(true);
    } catch (err) {
      setError("Could not access camera. Please check permissions.");
    }
  }

  async function capture() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const w = video.videoWidth || video.clientWidth || 640;
    const h = video.videoHeight || video.clientHeight || 480;
    canvas.width = w;
    canvas.height = h;

    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.drawImage(video, 0, 0, w, h);
    }
    const url = canvas.toDataURL("image/png");
    setPhoto(url);
    onCapture?.(url);

    // Stop tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setStreaming(false);

    // Auto-upload the captured frame so the hidden input carries a real
    // forge_files id — this makes CameraCapture drop-in compatible with
    // enclosing Forms and the workflow-dispatch layer (same convention as
    // FileUpload). Without the upload the Form submits a raw base64 blob
    // that the runtime can't resolve to an image.
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/png"),
    );
    if (!blob) { setError("Could not encode captured frame."); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", new File([blob], `camera-${Date.now()}.png`, { type: "image/png" }));
      const res = await fetch(uploadUrl, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`upload failed (${res.status})`);
      const ref = await res.json() as { id?: string };
      if (ref?.id) {
        setUploadedId(ref.id);
        onUploaded?.(ref.id);
      }
    } catch (e) {
      setError("Uploaded photo failed. Please retake.");
    } finally {
      setUploading(false);
    }
  }

  function retake() {
    setPhoto(null);
    setError(null);
    setUploadedId("");
  }

  return (
    <div
      data-camera-capture=""
      className="flex flex-col gap-3"
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label && (
        <span className="text-sm font-medium text-foreground">{label}</span>
      )}
      {/* Hidden control carries the uploaded file id for enclosing Forms.
       * Only emitted when a photo has actually been captured + uploaded —
       * an always-rendered empty hidden input would clobber a sibling
       * FileUpload sharing the same `name` (FormData collapses same-name
       * entries last-wins), so an unused camera silently blanks the field. */}
      {uploadedId && (
        <input type="hidden" name={name} value={uploadedId} readOnly />
      )}

      {/* Preview area */}
      <div className="relative overflow-hidden rounded-md border border-border bg-muted aspect-video flex items-center justify-center">
        {streaming && (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="w-full h-full object-cover"
          />
        )}
        {photo && !streaming && (
          <img
            src={photo}
            alt="Captured photo"
            className="w-full h-full object-cover"
          />
        )}
        {!streaming && !photo && (
          <span className="text-muted-foreground text-sm">
            Camera preview will appear here
          </span>
        )}
        {/* Hidden canvas for frame capture */}
        <canvas ref={canvasRef} className="hidden" />
      </div>

      {error && (
        <span className="text-sm text-foreground" role="alert">
          {error}
        </span>
      )}

      {/* Controls */}
      <div className="flex gap-2">
        {!streaming && !photo && (
          <button
            type="button"
            aria-label="Start camera"
            onClick={startCamera}
            className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium"
          >
            Start Camera
          </button>
        )}
        {streaming && (
          <button
            type="button"
            aria-label="Capture photo"
            onClick={capture}
            disabled={uploading}
            className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? "Uploading…" : (captureLabel ?? "Capture Photo")}
          </button>
        )}
        {photo && (
          <button
            type="button"
            aria-label="Retake photo"
            onClick={retake}
            className="px-4 py-2 rounded-md border border-border bg-muted text-foreground text-sm font-medium"
          >
            Retake
          </button>
        )}
      </div>
    </div>
  );
}
