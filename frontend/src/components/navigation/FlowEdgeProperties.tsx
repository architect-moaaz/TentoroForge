"use client";

import { useNavigationStore } from "@/stores/navigation";
import type { NavEdgeSerialized } from "@/types/navigation";

interface FlowEdgePropertiesProps {
  edge: NavEdgeSerialized;
}

const TRIGGER_OPTIONS = [
  { value: "link", label: "Navigation Link", description: "Sidebar or inline link" },
  { value: "redirect", label: "Auto Redirect", description: "After form submit or auth" },
  { value: "back", label: "Back Navigation", description: "Return to previous page" },
];

export function FlowEdgeProperties({ edge }: FlowEdgePropertiesProps) {
  const { edges, setEdges } = useNavigationStore();

  const updateEdge = (updates: Partial<NavEdgeSerialized["data"]>) => {
    setEdges(
      edges.map((e) =>
        e.id === edge.id ? { ...e, data: { ...e.data, ...updates } } : e,
      ),
    );
  };

  return (
    <div className="space-y-4 p-3">
      <div>
        <h3 className="text-sm font-medium mb-3">Connection Properties</h3>

        {/* Label */}
        <div className="space-y-1.5 mb-3">
          <label className="text-xs text-muted-foreground">Label</label>
          <input
            type="text"
            value={edge.data?.label || ""}
            onChange={(e) => updateEdge({ label: e.target.value })}
            className="w-full px-2 py-1.5 text-sm border rounded-md"
            placeholder="e.g., row click, submit, sign in"
          />
        </div>

        {/* Navigation Type */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Trigger Type</label>
          <div className="space-y-1">
            {TRIGGER_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex items-start gap-2 p-2 rounded-md border cursor-pointer transition-colors ${
                  (edge.data?.navType || "link") === opt.value
                    ? "border-blue-500 bg-blue-50"
                    : "border-transparent hover:bg-accent"
                }`}
              >
                <input
                  type="radio"
                  name={`trigger-${edge.id}`}
                  value={opt.value}
                  checked={(edge.data?.navType || "link") === opt.value}
                  onChange={() => updateEdge({ navType: opt.value as "link" | "redirect" | "back" })}
                  className="mt-0.5"
                />
                <div>
                  <div className="text-xs font-medium">{opt.label}</div>
                  <div className="text-[10px] text-muted-foreground">{opt.description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
