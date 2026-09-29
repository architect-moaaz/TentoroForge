"use client";
// The app SDK — the camera. A page that takes a picture or reads a barcode
// uses these, never a placeholder frame: SnapIT's snap page drew a dashed box
// captioned "No image captured yet", its "Take photo" opened a file picker and
// its barcode tab was a box to type digits into (2026-09-29).
//
// Both start the device's camera in the page (getUserMedia: https or
// localhost), stop it when they unmount, and say in words why a camera is not
// there (none on the device, permission declined).

import * as React from "react";

/** What a scan read, and the frame it read it from (an image data URL) —
 *  so a code no catalogue knows can still be identified from the picture. */
export type ScannedCode = { value: string; format: string; image?: string };

type CameraState = { status: "starting" | "live" | "unavailable"; reason: string };

function whyNot(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Camera access was declined. Allow the camera for this site in your browser to use it.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError") return "The camera is in use by another app.";
  return "The camera could not be started.";
}

function useCamera(facing: "environment" | "user", active: boolean) {
  const video = React.useRef<HTMLVideoElement>(null);
  const [state, setState] = React.useState<CameraState>({ status: "starting", reason: "" });
  React.useEffect(() => {
    if (!active) return;
    let stream: MediaStream | null = null;
    let gone = false;
    setState({ status: "starting", reason: "" });
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setState({ status: "unavailable", reason: "This browser cannot open the camera here." });
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then(async (s) => {
        if (gone) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        const v = video.current;
        if (v) {
          v.srcObject = s;
          await v.play().catch(() => {});
        }
        setState({ status: "live", reason: "" });
      })
      .catch((e) => { if (!gone) setState({ status: "unavailable", reason: whyNot(e) }); });
    return () => {
      gone = true;
      stream?.getTracks().forEach((t) => t.stop());
      if (video.current) video.current.srcObject = null;
    };
  }, [facing, active]);
  return { video, state };
}

/** The current frame, at most `max` pixels on its longer side. */
function grab(v: HTMLVideoElement, max: number, canvas?: HTMLCanvasElement): HTMLCanvasElement | null {
  const w = v.videoWidth, h = v.videoHeight;
  if (!w || !h) return null;
  const k = Math.min(1, max / Math.max(w, h));
  const c = canvas ?? document.createElement("canvas");
  c.width = Math.round(w * k);
  c.height = Math.round(h * k);
  c.getContext("2d", { willReadFrequently: true })?.drawImage(v, 0, 0, c.width, c.height);
  return c;
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

// One self-contained frame: the viewfinder with its controls ON it, as a
// camera app has them, so a page may set it in a box of any size and nothing
// falls outside (a page that clipped its box hid the shutter under the frame).
const Frame = ({ className, children }: { className?: string; children: React.ReactNode }) => (
  <div className={"relative aspect-[4/5] w-full overflow-hidden rounded-md bg-black " + (className ?? "")}>{children}</div>
);
const Controls = ({ children }: { children: React.ReactNode }) => (
  <div className="absolute inset-x-0 bottom-0 flex flex-col items-center gap-2 bg-gradient-to-t from-black/70 to-transparent p-4 pt-10">
    {children}
  </div>
);

/** The live camera: a viewfinder and a shutter. `onCapture` gets the frame as
 *  an image data URL. Where there is no camera, or the person declines it, it
 *  offers a picture from the device instead. */
export function CameraCapture({
  onCapture, label = "Take photo", facing = "environment", maxSize = 1600, className,
}: {
  onCapture: (dataUrl: string) => void; label?: string; facing?: "environment" | "user"; maxSize?: number; className?: string;
}) {
  const { video, state } = useCamera(facing, true);
  const file = React.useRef<HTMLInputElement>(null);
  const shoot = () => {
    const c = video.current && grab(video.current, maxSize);
    if (c) onCapture(c.toDataURL("image/jpeg", 0.9));
  };
  const pick = async (f: File | undefined) => { if (f) onCapture(await readFile(f)); };
  return (
    <Frame className={className}>
      <video ref={video} playsInline muted autoPlay aria-label="Camera viewfinder"
        className={"h-full w-full object-cover " + (state.status === "live" ? "" : "invisible")} />
      {state.status !== "live" && (
        <div className="absolute inset-0 flex items-center justify-center p-6 pb-24 text-center text-sm text-white/80">
          {state.status === "starting" ? "Starting the camera…" : state.reason}
        </div>
      )}
      <Controls>
        {state.status === "live" ? (
          <button type="button" onClick={shoot} aria-label={label}
            className="flex items-center gap-3 rounded-full bg-white/15 py-1.5 pl-1.5 pr-5 text-sm font-semibold text-white ring-1 ring-white/40 hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
            <span className="h-12 w-12 rounded-full border-4 border-white bg-white/90" />
            {label}
          </button>
        ) : state.status === "unavailable" ? (
          <button type="button" onClick={() => file.current?.click()}
            className="rounded-md bg-white px-4 py-2.5 text-sm font-semibold text-black hover:bg-white/90">
            Choose a photo instead
          </button>
        ) : null}
      </Controls>
      <input ref={file} type="file" accept="image/*" className="hidden"
        onChange={(e) => pick(e.target.files?.[0])} />
    </Frame>
  );
}

// Formats by the names people read on a pack: "EAN-13", "UPC-A", "QR".
const FORMAT_NAMES: Record<string, string> = {
  ean_13: "EAN-13", ean_8: "EAN-8", upc_a: "UPC-A", upc_e: "UPC-E", qr_code: "QR", code_128: "CODE-128",
  code_39: "CODE-39", code_93: "CODE-93", codabar: "CODABAR", itf: "ITF", data_matrix: "DATA-MATRIX",
  pdf417: "PDF417", aztec: "AZTEC",
};
const formatName = (raw: string) => FORMAT_NAMES[raw.toLowerCase().replace(/-/g, "_")] ?? raw.toUpperCase().replace(/_/g, "-");

type Decoder = (c: HTMLCanvasElement) => Promise<ScannedCode | null>;

/** The browser's own detector where it has one (Chrome, Android); the ZXing
 *  reader everywhere else (Safari, Firefox). */
async function makeDecoder(): Promise<Decoder> {
  const Native = (globalThis as { BarcodeDetector?: any }).BarcodeDetector;
  if (Native) {
    try {
      const formats: string[] = await Native.getSupportedFormats();
      if (formats.length) {
        const d = new Native({ formats });
        return async (c) => {
          const [hit] = await d.detect(c);
          return hit ? { value: String(hit.rawValue), format: formatName(String(hit.format)) } : null;
        };
      }
    } catch { /* fall through to ZXing */ }
  }
  const [{ BrowserMultiFormatReader }, lib] = await Promise.all([import("@zxing/browser"), import("@zxing/library")]);
  const hints = new Map();
  hints.set(lib.DecodeHintType.TRY_HARDER, true);
  const reader = new BrowserMultiFormatReader(hints);
  return async (c) => {
    try {
      const r = reader.decodeFromCanvas(c);
      return { value: r.getText(), format: formatName(String(lib.BarcodeFormat[r.getBarcodeFormat()])) };
    } catch {
      return null; // no code in this frame
    }
  };
}

/** Reads a barcode or QR code from the live camera, continuously, and calls
 *  `onScan` once with what it read. "Scan again" starts over. */
export function BarcodeScanner({
  onScan, label = "Point the camera at the barcode", className,
}: {
  onScan: (code: ScannedCode) => void; label?: string; className?: string;
}) {
  const [found, setFound] = React.useState<ScannedCode | null>(null);
  const { video, state } = useCamera("environment", !found);
  const onScanRef = React.useRef(onScan);
  onScanRef.current = onScan;
  React.useEffect(() => {
    if (state.status !== "live" || found) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const canvas = document.createElement("canvas");
    makeDecoder().then((decode) => {
      const tick = async () => {
        if (stop) return;
        const c = video.current && grab(video.current, 1280, canvas);
        const hit = c ? await decode(c).catch(() => null) : null;
        if (stop) return;
        if (hit && hit.value) {
          stop = true;
          try { hit.image = c!.toDataURL("image/jpeg", 0.85); } catch { /* a tainted frame keeps the code only */ }
          if (typeof navigator !== "undefined") navigator.vibrate?.(40);
          setFound(hit);
          onScanRef.current(hit);
          return;
        }
        timer = setTimeout(tick, 250);
      };
      tick();
    });
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [state.status, found, video]);
  return (
    <Frame className={className}>
      {!found && (
        <video ref={video} playsInline muted autoPlay aria-label="Camera viewfinder"
          className={"h-full w-full object-cover " + (state.status === "live" ? "" : "invisible")} />
      )}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center pb-10">
        <div className={"h-28 w-[75%] rounded-md border-2 " + (found ? "border-green-400" : "border-white/70")} />
      </div>
      <Controls>
        <p className="text-center text-sm text-white/90" role="status">
          {found ? `Scanned ${found.value}` : state.status === "live" ? label
            : state.status === "starting" ? "Starting the camera…" : state.reason}
        </p>
        {found && (
          <button type="button" onClick={() => setFound(null)}
            className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-white/90">
            Scan again
          </button>
        )}
      </Controls>
    </Frame>
  );
}
