import type { ReactNode } from "react";

export function TokenGroup({ name, children }: { name: string; children: ReactNode }) {
  return (
    <details open style={{ marginBottom: 8 }}>
      <summary style={{ fontSize: 11, textTransform: "uppercase", color: "#6b7280", letterSpacing: "0.05em", cursor: "pointer", padding: "4px 0" }}>
        {name}
      </summary>
      <div style={{ paddingLeft: 8 }}>{children}</div>
    </details>
  );
}
