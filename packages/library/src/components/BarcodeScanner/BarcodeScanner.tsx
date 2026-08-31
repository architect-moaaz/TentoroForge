"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { BarcodeScannerPropsType } from "./BarcodeScanner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface BarcodeScannerProps extends BarcodeScannerPropsType {
  style?: StyleSlotT;
  onDetect?: (value: string) => void;
}

type DetectedBarcode = { rawValue: string };
type Detector = { detect: (src: ImageBitmapSource) => Promise<DetectedBarcode[]> };
type DetectorCtor = new (opts?: { formats?: string[] }) => Detector;

const POLL_MS = 200;

export function BarcodeScanner({
  name = "barcode",
  label,
  hint,
  formats,
  bind: _bind,
  autoSubmit,
  className,
  style,
  onDetect,
}: BarcodeScannerProps) {
  const [code, setCode] = React.useState("");
  const [scanning, setScanning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileRef = React.useRef<HTMLInputElement | null>(null);
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const submittedRef = React.useRef("");

  const supported =
    typeof window !== "undefined" && "BarcodeDetector" in window;
  const inNativeShell =
    typeof window !== "undefined" && "ReactNativeWebView" in window;

  const detectorRef = React.useRef<Detector | null>(null);
  const getDetector = React.useCallback((): Detector | null => {
    if (!supported) return null;
    if (!detectorRef.current) {
      try {
        const Ctor = (window as unknown as { BarcodeDetector: DetectorCtor }).BarcodeDetector;
        detectorRef.current = new Ctor(
          formats && formats.length ? { formats } : undefined
        );
      } catch {
        return null;
      }
    }
    return detectorRef.current;
  }, [supported, formats]);

  const stopCamera = React.useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
  }, []);

  React.useEffect(() => stopCamera, [stopCamera]);

  // Native-shell bridge: a wrapping mobile app (React Native WebView) scans
  // with the device camera and hands the decoded value to the page via
  // `window.dispatchEvent(new CustomEvent('forge-barcode', {detail}))`.
  React.useEffect(() => {
    const onNative = (e: Event) => {
      const value = String((e as CustomEvent).detail ?? "").trim();
      if (value) {
        setCode(value);
        setError(null);
        onDetect?.(value);
      }
    };
    window.addEventListener("forge-barcode", onNative);
    return () => window.removeEventListener("forge-barcode", onNative);
  }, [onDetect]);

  // Scan-to-search: once a code lands (camera, image, or native bridge),
  // submit the enclosing Form so the user never has to press the button.
  // Runs post-render, so the hidden <input> is already in the DOM.
  React.useEffect(() => {
    if (!code) {
      submittedRef.current = "";
      return;
    }
    if (!autoSubmit || submittedRef.current === code) return;
    submittedRef.current = code;
    rootRef.current?.closest("form")?.requestSubmit();
  }, [autoSubmit, code]);

  const found = React.useCallback(
    (value: string) => {
      setCode(value);
      setError(null);
      stopCamera();
      onDetect?.(value);
    },
    [onDetect, stopCamera]
  );

  const startCamera = React.useCallback(async () => {
    const detector = getDetector();
    if (!detector) {
      setError(inNativeShell ? "Use the app's Scan button below to scan with your camera." : "Barcode detection isn't supported in this browser. Try dropping an image instead, or use Chrome/Edge.");
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false,
      });
      streamRef.current = stream;
      setScanning(true);
      // Wait a tick for the <video> to mount before attaching the stream.
      requestAnimationFrame(() => {
        const v = videoRef.current;
        if (!v) return;
        v.srcObject = stream;
        void v.play();
        const tick = async () => {
          const video = videoRef.current;
          if (!video || !streamRef.current) return;
          if (video.readyState >= 2) {
            try {
              const codes = await detector.detect(video);
              if (codes.length && codes[0].rawValue) {
                found(codes[0].rawValue);
                return;
              }
            } catch {
              /* frame not ready — keep polling */
            }
          }
          timerRef.current = setTimeout(tick, POLL_MS);
        };
        timerRef.current = setTimeout(tick, POLL_MS);
      });
    } catch {
      setError("Couldn't access the camera. Check permissions and try again.");
      setScanning(false);
    }
  }, [getDetector, found]);

  const decodeFile = React.useCallback(
    async (file: File) => {
      const detector = getDetector();
      if (!detector) {
        setError(inNativeShell ? "Use the app's Scan button below to scan with your camera." : "Barcode detection isn't supported in this browser. Use Chrome/Edge.");
        return;
      }
      if (!file.type.startsWith("image/")) {
        setError("Drop an image file containing a barcode.");
        return;
      }
      try {
        const bitmap = await createImageBitmap(file);
        const codes = await detector.detect(bitmap);
        bitmap.close();
        if (codes.length && codes[0].rawValue) found(codes[0].rawValue);
        else setError("No barcode found in that image. Try a sharper photo.");
      } catch {
        setError("Couldn't read that image.");
      }
    },
    [getDetector, found]
  );

  return (
    <div
      ref={rootRef}
      data-barcode-scanner=""
      className={className}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label && (
        <div className="text-sm font-medium text-foreground mb-2">{label}</div>
      )}

      {/* Rendered only once a code exists so an empty value never clobbers a
          sibling field of the same name (same rule as CameraCapture). */}
      {code && <input type="hidden" name={name} value={code} readOnly />}

      {code ? (
        <div className="flex items-center gap-3 rounded-md border border-input bg-background p-3">
          <span className="text-sm text-muted-foreground">Barcode</span>
          <span data-testid="barcode-value" className="font-mono text-sm font-semibold text-foreground">
            {code}
          </span>
          <button
            type="button"
            onClick={() => { setCode(""); setError(null); }}
            className="ms-auto text-sm text-muted-foreground underline-offset-2 hover:underline"
          >
            Scan again
          </button>
        </div>
      ) : inNativeShell ? (
        <div className="rounded-md border border-dashed border-input bg-background p-4 text-center">
          <p className="text-sm font-medium text-foreground">
            Tap the <span className="font-bold">&#9638; Scan</span> button (bottom right) to scan with your camera.
          </p>
          {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="relative overflow-hidden rounded-md border border-border bg-muted aspect-video flex items-center justify-center">
            {scanning ? (
              <>
                <video
                  ref={videoRef}
                  className="h-full w-full object-cover"
                  muted
                  playsInline
                />
                {/* Reticle overlay */}
                <div className="pointer-events-none absolute inset-x-[15%] inset-y-[30%] rounded border-2 border-white/80" />
              </>
            ) : (
              <span className="text-sm text-muted-foreground">
                Camera preview
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={scanning ? stopCamera : startCamera}
              className="inline-flex items-center rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium text-foreground shadow-sm hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {scanning ? "Stop camera" : "Scan with camera"}
            </button>
            <span className="text-sm text-muted-foreground">or</span>
            <div
              role="button"
              tabIndex={0}
              aria-label="Drop a barcode image or click to browse"
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") fileRef.current?.click();
              }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void decodeFile(file);
              }}
              className={
                "flex-1 min-w-[12rem] cursor-pointer rounded-md border border-dashed px-3 py-2 text-center text-sm transition-colors " +
                (dragOver
                  ? "border-ring bg-accent text-accent-foreground"
                  : "border-input bg-background text-muted-foreground hover:bg-accent/50")
              }
            >
              Drop a barcode image here, or click to browse
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void decodeFile(file);
                e.target.value = "";
              }}
            />
          </div>

          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
          {error && (
            <p data-testid="barcode-error" className="text-sm" style={{ color: "#dc2626" }}>
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
