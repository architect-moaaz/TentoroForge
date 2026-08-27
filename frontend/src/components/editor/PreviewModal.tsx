"use client";
import * as React from "react";
import { X, ExternalLink, RotateCw, Smartphone, Tablet, Monitor, Loader2 } from "lucide-react";

type Device = "mobile" | "tablet" | "desktop";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Full URL of the render-scaffold page to preview. */
  url: string;
  /** Initial device — toggleable inside the modal. */
  initialDevice?: Device;
}

const DEVICE_DIMENSIONS: Record<Device, { width: number; height: number; label: string }> = {
  mobile:  { width: 375,  height: 667,  label: "iPhone" },
  tablet:  { width: 768,  height: 1024, label: "iPad"   },
  desktop: { width: 1280, height: 800,  label: "Desktop" },
};

/**
 * PreviewModal — iframes the render-scaffold preview inside an overlay.
 *
 * Sized to mimic the requested device viewport (mobile/tablet/desktop).
 * Esc to close, click backdrop to close, "Open in new tab" button for
 * users who want a real browser context (e.g. to test deep links or
 * inspect with devtools without going through the iframe). A reload
 * button forces a fresh fetch with a new cache-busting query string.
 */
export function PreviewModal({ open, onClose, url, initialDevice = "desktop" }: Props) {
  const [device, setDevice] = React.useState<Device>(initialDevice);
  const [iframeKey, setIframeKey] = React.useState(0);
  const [loading, setLoading] = React.useState(true);

  // Re-sync device when the parent toolbar's device changes between
  // open events (mounting the modal once and reopening preserves state
  // otherwise).
  React.useEffect(() => {
    if (open) {
      setDevice(initialDevice);
      setIframeKey((k) => k + 1);
      setLoading(true);
    }
  }, [open, initialDevice]);

  // Esc closes.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const dim = DEVICE_DIMENSIONS[device];

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        // Backdrop click closes; clicks inside the modal don't bubble.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[95vw] h-[92vh] max-w-[1400px] flex flex-col rounded-lg bg-background shadow-2xl border overflow-hidden">
        {/* Toolbar */}
        <div className="h-11 px-3 flex items-center gap-1.5 border-b bg-muted/30 flex-shrink-0">
          <span className="text-sm font-medium mr-2">Preview</span>

          {/* Device toggles */}
          {(["mobile", "tablet", "desktop"] as Device[]).map((d) => {
            const Icon = d === "mobile" ? Smartphone : d === "tablet" ? Tablet : Monitor;
            const isActive = d === device;
            return (
              <button
                key={d}
                onClick={() => {
                  setDevice(d);
                  setLoading(true);
                  setIframeKey((k) => k + 1);
                }}
                className={
                  "h-7 w-7 grid place-items-center rounded text-xs transition-colors " +
                  (isActive
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
                title={DEVICE_DIMENSIONS[d].label}
                aria-label={DEVICE_DIMENSIONS[d].label}
              >
                <Icon size={14} />
              </button>
            );
          })}

          <span className="ml-2 text-[11px] text-muted-foreground tabular-nums">
            {dim.width}×{dim.height}
          </span>

          <div className="flex-1" />

          <button
            onClick={() => {
              setLoading(true);
              setIframeKey((k) => k + 1);
            }}
            className="h-7 w-7 grid place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="Reload preview"
            aria-label="Reload"
          >
            <RotateCw size={14} />
          </button>

          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="h-7 px-2 inline-flex items-center gap-1 rounded text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="Open in new tab"
          >
            <ExternalLink size={13} />
            New tab
          </a>

          <button
            onClick={onClose}
            className="h-7 w-7 grid place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="Close (Esc)"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Frame area */}
        <div className="flex-1 min-h-0 grid place-items-center bg-muted/20 overflow-auto p-4">
          <div
            className="relative bg-white shadow-lg border rounded overflow-hidden"
            style={{
              width: device === "desktop" ? "100%" : dim.width,
              maxWidth: device === "desktop" ? dim.width : undefined,
              height: device === "desktop" ? "100%" : dim.height,
              maxHeight: device === "desktop" ? dim.height : undefined,
            }}
          >
            {loading && (
              <div className="absolute inset-0 grid place-items-center bg-background/60 z-10 pointer-events-none">
                <Loader2 size={20} className="animate-spin text-muted-foreground" />
              </div>
            )}
            <iframe
              key={iframeKey}
              src={url}
              title="Preview"
              className="w-full h-full block border-0"
              onLoad={() => setLoading(false)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
