"use client";

import { useRef, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import { useBridge } from "@/hooks/useBridge";
import { useVisualEditorStore } from "@/stores/visual-editor";
import type { DeviceSize, ElementInfo } from "@/types/visual-editor";

const DEVICE_WIDTHS: Record<DeviceSize, string> = {
  desktop: "100%",
  tablet: "768px",
  mobile: "375px",
};

// Track bridge injection per project to survive component remounts
const bridgeInjectedFor = new Set<string>();

export interface CanvasFrameHandle {
  reload: () => void;
  notifyEditComplete: () => void;
  scrollTo: (xpath: string) => void;
  highlight: (xpath: string) => void;
}

interface CanvasFrameProps {
  previewPort: number;
  projectId: string;
  onBridgeReady?: () => void;
}

export const CanvasFrame = forwardRef<CanvasFrameHandle, CanvasFrameProps>(
  function CanvasFrame({ previewPort, projectId, onBridgeReady }, ref) {
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const bridge = useBridge({ iframeRef });
    const currentRoute = useVisualEditorStore((s) => s.currentRoute);
    const devicePreview = useVisualEditorStore((s) => s.devicePreview);
    const setShowActionPopover = useVisualEditorStore((s) => s.setShowActionPopover);
    const selectedElement = useVisualEditorStore((s) => s.selectedElement);

    // Route through the platform backend's reverse-proxy at
    // /api/projects/<id>/preview/serve/... so the iframe works
    // whether the backend runs on the same host (local dev) or in a
    // container the browser can't reach directly (UAT/prod). The
    // generated Next app is spawned with NEXT_BASE_PATH set to the
    // same prefix, so page + asset URLs it emits already match.
    // previewPort is retained to trigger a re-mount when a new dev
    // server comes up, but its value is not in the URL anymore.
    const API = process.env.NEXT_PUBLIC_API_URL ?? "";
    const proxyBase = `${API}/api/projects/${projectId}/preview/serve`;
    const route = currentRoute || "/";
    const src = previewPort
      ? `${proxyBase}${route}`
      : "about:blank";
    const width = DEVICE_WIDTHS[devicePreview];

    const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Expose reload, notifyEditComplete, scrollTo, highlight to parent
    useImperativeHandle(ref, () => ({
      reload: () => {
        if (iframeRef.current) {
          iframeRef.current.src = iframeRef.current.src;
        }
      },
      scrollTo: (xpath: string) => bridge.scrollTo(xpath),
      highlight: (xpath: string) => bridge.highlight(xpath),
      notifyEditComplete: () => {
        const iframe = iframeRef.current;
        if (!iframe?.contentWindow) {
          // No iframe — fall back to full reload
          if (iframe) iframe.src = iframe.src;
          return;
        }

        // Send edit-complete command to bridge with current selected xpath
        const xpath = selectedElement?.xpath || null;
        iframe.contentWindow.postMessage(
          { type: "design2ui:edit-complete", payload: { xpath } },
          "*",
        );

        // 3s fallback: if bridge never responds with edit-settled, force reload
        if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = setTimeout(() => {
          fallbackTimerRef.current = null;
          if (iframe) iframe.src = iframe.src;
        }, 3000);
      },
    }));

    // Listen for edit-settled from bridge to cancel fallback reload
    useEffect(() => {
      function handleMessage(e: MessageEvent) {
        if (e.data?.type === "design2ui:edit-settled") {
          if (fallbackTimerRef.current) {
            clearTimeout(fallbackTimerRef.current);
            fallbackTimerRef.current = null;
          }
        }
      }
      window.addEventListener("message", handleMessage);
      return () => window.removeEventListener("message", handleMessage);
    }, []);

    // Inject bridge once per project (survives remounts)
    useEffect(() => {
      if (bridgeInjectedFor.has(projectId)) return;

      let cancelled = false;

      async function injectBridge() {
        try {
          const token = localStorage.getItem("token");
          await fetch(
            `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/bridge/inject`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
              },
            },
          );
          if (cancelled) return;
          bridgeInjectedFor.add(projectId);
          // Reload iframe to pick up the bridge script
          if (iframeRef.current) {
            iframeRef.current.src = iframeRef.current.src;
          }
          onBridgeReady?.();
        } catch {
          // Bridge injection failed — editor still works, just without overlays
        }
      }

      const iframe = iframeRef.current;
      if (iframe) {
        // Wait for first load, then inject
        const handler = () => { injectBridge(); };
        iframe.addEventListener("load", handler, { once: true });
        return () => {
          cancelled = true;
          iframe.removeEventListener("load", handler);
        };
      }
    }, [projectId, onBridgeReady]);

    // Compute popover position when an element is selected
    const computePopoverPosition = useCallback(
      (el: ElementInfo) => {
        const iframe = iframeRef.current;
        const container = containerRef.current;
        if (!iframe || !container) return null;

        const iframeRect = iframe.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();

        // Element rect is relative to the iframe viewport
        const elTop = el.rect.top + iframeRect.top - containerRect.top;
        const elLeft = el.rect.left + iframeRect.left - containerRect.left;
        const elBottom = elTop + el.rect.height;

        // Position popover below the element, or above if not enough space
        const spaceBelow = containerRect.height - elBottom;
        const popoverHeight = 180; // approximate

        let top: number;
        if (spaceBelow > popoverHeight + 8) {
          top = elBottom + 8;
        } else {
          top = Math.max(8, elTop - popoverHeight - 8);
        }

        // Center horizontally relative to element, clamped to container
        const left = Math.min(
          Math.max(8, elLeft + el.rect.width / 2 - 80),
          containerRect.width - 250,
        );

        return { top, left };
      },
      [],
    );

    // Show action popover when element is selected
    useEffect(() => {
      if (selectedElement) {
        const pos = computePopoverPosition(selectedElement);
        if (pos) {
          setShowActionPopover(true, pos);
        }
      } else {
        setShowActionPopover(false);
      }
    }, [selectedElement, computePopoverPosition, setShowActionPopover]);

    // Dismiss popover when clicking on the canvas background (not an element)
    const handleCanvasClick = useCallback(
      (e: React.MouseEvent) => {
        // Only dismiss if the click is directly on the container, not the iframe
        if (e.target === containerRef.current) {
          useVisualEditorStore.getState().setSelectedElement(null);
          setShowActionPopover(false);
        }
      },
      [setShowActionPopover],
    );

    return (
      <div
        ref={containerRef}
        className="flex-1 flex items-start justify-center overflow-auto bg-muted/20 p-4 relative"
        onClick={handleCanvasClick}
      >
        <div
          className="bg-white shadow-lg rounded-lg overflow-hidden transition-all duration-200"
          style={{
            width,
            maxWidth: "100%",
            height: "100%",
          }}
        >
          <iframe
            ref={iframeRef}
            src={src}
            className="w-full h-full border-0"
            title="App Preview"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          />
        </div>
      </div>
    );
  },
);
