import { useEffect, useState } from "react";
import type { NodeId } from "../../state/types";

type Rect = { top: number; left: number; width: number; height: number };

export function useNodeRect(id: NodeId | null): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);

  useEffect(() => {
    if (!id) { setRect(null); return; }
    const update = () => {
      const el = document.querySelector(`[data-node-id="${CSS.escape(id)}"]`) as HTMLElement | null;
      if (!el) { setRect(null); return; }
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    update();
    const ro = new ResizeObserver(update);
    document.documentElement && ro.observe(document.documentElement);
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [id]);

  return rect;
}
