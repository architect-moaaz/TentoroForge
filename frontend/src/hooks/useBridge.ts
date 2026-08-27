import { useEffect, useCallback, useRef } from "react";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { transformBridgeTree } from "@/lib/section-tree-utils";
import type { ElementInfo } from "@/types/visual-editor";

const PREFIX = "design2ui:";

interface UseBridgeOptions {
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
}

export function useBridge({ iframeRef }: UseBridgeOptions) {
  const readyRef = useRef(false);

  const setSelectedElement = useVisualEditorStore((s) => s.setSelectedElement);
  const setHoveredElement = useVisualEditorStore((s) => s.setHoveredElement);

  // Listen for messages from the bridge
  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      if (!e.data || typeof e.data.type !== "string") return;
      if (!e.data.type.startsWith(PREFIX)) return;

      const type = e.data.type.slice(PREFIX.length);
      const payload = e.data.payload;

      switch (type) {
        case "ready":
          readyRef.current = true;
          break;
        case "hover":
          setHoveredElement(payload as ElementInfo);
          break;
        case "select":
          setSelectedElement(payload as ElementInfo);
          break;
        case "deselect":
          setSelectedElement(null);
          break;
        case "tree":
          if (payload?.tree) {
            const sectionTree = transformBridgeTree(payload.tree);
            useVisualEditorStore.getState().setSectionTree(sectionTree);
          }
          break;
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [setSelectedElement, setHoveredElement]);

  const sendCommand = useCallback(
    (type: string, payload: unknown = {}) => {
      const iframe = iframeRef.current;
      if (!iframe?.contentWindow) return;
      iframe.contentWindow.postMessage(
        { type: PREFIX + type, payload },
        "*",
      );
    },
    [iframeRef],
  );

  const scrollTo = useCallback(
    (xpath: string) => sendCommand("scroll-to", { xpath }),
    [sendCommand],
  );
  const highlight = useCallback(
    (xpath: string) => sendCommand("highlight", { xpath }),
    [sendCommand],
  );
  const requestTree = useCallback(
    () => sendCommand("get-tree"),
    [sendCommand],
  );

  return {
    ready: readyRef.current,
    sendCommand,
    scrollTo,
    highlight,
    requestTree,
  };
}
