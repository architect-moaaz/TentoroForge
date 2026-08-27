"use client";

import { useCallback } from "react";
import {
  Database,
  Table2,
  BookOpen,
  Trash2,
  LayoutGrid,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useDecisionStore } from "@/stores/decision";
import type { DRDNodeType } from "@/types/decision";

interface DRDToolbarProps {
  onAutoLayout: () => void;
  onSave: () => void;
  isSaving?: boolean;
}

const NODE_TYPES: {
  type: DRDNodeType;
  label: string;
  icon: typeof Table2;
  color: string;
}[] = [
  {
    type: "inputData",
    label: "Input Data",
    icon: Database,
    color: "text-sky-600",
  },
  {
    type: "decision",
    label: "Decision",
    icon: Table2,
    color: "text-indigo-600",
  },
  {
    type: "knowledgeSource",
    label: "Knowledge",
    icon: BookOpen,
    color: "text-amber-600",
  },
];

export function DRDToolbar({ onAutoLayout, onSave, isSaving }: DRDToolbarProps) {
  const selectedDRDNodeId = useDecisionStore((s) => s.selectedDRDNodeId);
  const removeDRDNode = useDecisionStore((s) => s.removeDRDNode);
  const graph = useDecisionStore((s) => s.currentGraph);

  const handleAddNode = useCallback(
    (type: DRDNodeType) => {
      const store = useDecisionStore.getState();
      const nodeCount = graph?.nodes.filter((n) => n.type === type).length ?? 0;
      const defaultLabel =
        type === "inputData"
          ? `Input Data ${nodeCount + 1}`
          : type === "knowledgeSource"
            ? `Knowledge Source ${nodeCount + 1}`
            : `Decision ${nodeCount + 1}`;

      store.addDRDNode({
        id: `drd_${type}_${Date.now()}`,
        type,
        label: defaultLabel,
        position: {
          x: 100 + Math.random() * 200,
          y: 100 + Math.random() * 200,
        },
      });
    },
    [graph?.nodes],
  );

  const handleDelete = useCallback(() => {
    if (selectedDRDNodeId) {
      removeDRDNode(selectedDRDNodeId);
    }
  }, [selectedDRDNodeId, removeDRDNode]);

  const onDragStart = useCallback(
    (event: React.DragEvent, nodeType: DRDNodeType) => {
      event.dataTransfer.setData("application/drd-node-type", nodeType);
      event.dataTransfer.effectAllowed = "move";
    },
    [],
  );

  return (
    <div className="flex w-[140px] flex-col gap-2 border-r bg-muted/20 p-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-1">
        Add Nodes
      </div>

      {NODE_TYPES.map(({ type, label, icon: Icon, color }) => (
        <div
          key={type}
          draggable
          onDragStart={(e) => onDragStart(e, type)}
          className="cursor-grab"
        >
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full justify-start text-xs"
            onClick={() => handleAddNode(type)}
          >
            <Icon className={`mr-1.5 h-3.5 w-3.5 ${color}`} />
            {label}
          </Button>
        </div>
      ))}

      <Separator className="my-1" />

      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-1">
        Actions
      </div>

      <Button
        variant="outline"
        size="sm"
        className="h-8 w-full justify-start text-xs"
        onClick={handleDelete}
        disabled={!selectedDRDNodeId}
      >
        <Trash2 className="mr-1.5 h-3.5 w-3.5 text-red-500" />
        Delete
      </Button>

      <Button
        variant="outline"
        size="sm"
        className="h-8 w-full justify-start text-xs"
        onClick={onAutoLayout}
      >
        <LayoutGrid className="mr-1.5 h-3.5 w-3.5" />
        Auto-layout
      </Button>

      <Button
        variant="outline"
        size="sm"
        className="h-8 w-full justify-start text-xs"
        onClick={onSave}
        disabled={isSaving}
      >
        <Save className="mr-1.5 h-3.5 w-3.5" />
        Save
      </Button>
    </div>
  );
}
