"use client";
/** Click text to change it (UX-009): a box over the element, committed as one change. */
import { useEffect, useRef, useState } from "react";

import { useEditorStore } from "./store";
import type { ModelNode, Rect } from "./types";

export function InlineTextEditor({ node, rect, onDone }: { node: ModelNode; rect: Rect; onDone: () => void }) {
  const setText = useEditorStore((s) => s.setText);
  const [value, setValue] = useState(node.text ?? "");
  const ref = useRef<HTMLTextAreaElement>(null);
  const committed = useRef(false);

  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);

  const commit = async () => {
    if (committed.current) return;
    committed.current = true;
    if (value !== (node.text ?? "")) await setText(node.id, value);
    onDone();
  };

  return (
    <textarea ref={ref} value={value} aria-label="Edit text"
      className="absolute z-20 resize-none rounded border-2 border-primary bg-white p-1 text-sm text-black shadow-lg outline-none"
      style={{ top: rect.top, left: rect.left, width: Math.max(rect.width, 120), height: Math.max(rect.height, 32) }}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => void commit()}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void commit(); }
        if (e.key === "Escape") { committed.current = true; onDone(); }
      }} />
  );
}
