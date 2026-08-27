"use client";

import { useCallback, useMemo, useState } from "react";
import { X, Database, Table2, BookOpen, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDecisionStore } from "@/stores/decision";
import { DecisionTableEditor } from "./DecisionTableEditor";
import type {
  DRDNode,
  DecisionTableDefinition,
  HitPolicy,
} from "@/types/decision";

export function DRDNodePanel() {
  const selectedDRDNodeId = useDecisionStore((s) => s.selectedDRDNodeId);
  const graph = useDecisionStore((s) => s.currentGraph);
  const updateDRDNode = useDecisionStore((s) => s.updateDRDNode);
  const setSelectedDRDNodeId = useDecisionStore((s) => s.setSelectedDRDNodeId);
  const upsertDecisionTable = useDecisionStore((s) => s.upsertDecisionTable);

  const node = useMemo(
    () => graph?.nodes.find((n) => n.id === selectedDRDNodeId) ?? null,
    [graph?.nodes, selectedDRDNodeId],
  );

  if (!node) return null;

  return (
    <div className="flex w-[320px] flex-col border-l bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <NodeIcon type={node.type} />
          <span className="text-sm font-semibold capitalize">
            {node.type === "inputData"
              ? "Input Data"
              : node.type === "knowledgeSource"
                ? "Knowledge Source"
                : "Decision"}
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => setSelectedDRDNodeId(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* Common: Label */}
        <div className="space-y-1.5">
          <Label className="text-xs">Label</Label>
          <Input
            className="h-8 text-xs"
            value={node.label}
            onChange={(e) => updateDRDNode(node.id, { label: e.target.value })}
          />
        </div>

        <Separator />

        {/* Type-specific content */}
        {node.type === "inputData" && (
          <InputDataProperties node={node} onUpdate={updateDRDNode} />
        )}
        {node.type === "decision" && (
          <DecisionProperties
            node={node}
            onUpdate={updateDRDNode}
            tables={graph?.tables ?? {}}
            onTableChange={upsertDecisionTable}
          />
        )}
        {node.type === "knowledgeSource" && (
          <KnowledgeSourceProperties node={node} onUpdate={updateDRDNode} />
        )}
      </div>
    </div>
  );
}

function NodeIcon({ type }: { type: string }) {
  switch (type) {
    case "inputData":
      return <Database className="h-4 w-4 text-sky-600" />;
    case "knowledgeSource":
      return <BookOpen className="h-4 w-4 text-amber-600" />;
    default:
      return <Table2 className="h-4 w-4 text-indigo-600" />;
  }
}

// ---------------------------------------------------------------------------
// InputData properties panel
// ---------------------------------------------------------------------------

function InputDataProperties({
  node,
  onUpdate,
}: {
  node: DRDNode;
  onUpdate: (id: string, updates: Partial<DRDNode>) => void;
}) {
  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-xs">Variable Name</Label>
        <Input
          className="h-8 text-xs font-mono"
          placeholder="e.g. customerAge"
          value={node.variableName ?? ""}
          onChange={(e) =>
            onUpdate(node.id, { variableName: e.target.value })
          }
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">Variable Type</Label>
        <Select
          value={node.variableType ?? "any"}
          onValueChange={(v) =>
            onUpdate(node.id, {
              variableType: v as DRDNode["variableType"],
            })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="string" className="text-xs">
              String
            </SelectItem>
            <SelectItem value="number" className="text-xs">
              Number
            </SelectItem>
            <SelectItem value="boolean" className="text-xs">
              Boolean
            </SelectItem>
            <SelectItem value="date" className="text-xs">
              Date
            </SelectItem>
            <SelectItem value="any" className="text-xs">
              Any
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Decision properties panel (with inline decision table editor)
// ---------------------------------------------------------------------------

function DecisionProperties({
  node,
  onUpdate,
  tables,
  onTableChange,
}: {
  node: DRDNode;
  onUpdate: (id: string, updates: Partial<DRDNode>) => void;
  tables: Record<string, DecisionTableDefinition>;
  onTableChange: (table: DecisionTableDefinition) => void;
}) {
  const [showTableEditor, setShowTableEditor] = useState(true);

  // Get or create the linked decision table
  const tableId = node.decisionTableId;
  const table = tableId ? tables[tableId] : null;

  const handleCreateTable = useCallback(() => {
    const newTableId = `dt_${node.id}_${Date.now()}`;
    const newTable: DecisionTableDefinition = {
      id: newTableId,
      name: `${node.label} Table`,
      hitPolicy: "U" as HitPolicy,
      inputs: [{ id: `inp_1`, name: "input1", type: "string" }],
      outputs: [{ id: `out_1`, name: "output1", type: "string" }],
      rules: [],
    };
    onTableChange(newTable);
    onUpdate(node.id, { decisionTableId: newTableId });
  }, [node, onUpdate, onTableChange]);

  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-xs">Decision Table</Label>
        {table ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground flex-1 truncate">
                {table.name}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-[10px]"
                onClick={() => setShowTableEditor(!showTableEditor)}
              >
                {showTableEditor ? "Hide" : "Edit"}
              </Button>
            </div>
            {showTableEditor && (
              <div className="rounded border bg-muted/10 p-2">
                <DecisionTableEditor
                  table={table}
                  onChange={onTableChange}
                  compact
                />
              </div>
            )}
          </div>
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full text-xs"
            onClick={handleCreateTable}
          >
            <Table2 className="mr-1.5 h-3.5 w-3.5" />
            Create Decision Table
          </Button>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// KnowledgeSource properties panel
// ---------------------------------------------------------------------------

function KnowledgeSourceProperties({
  node,
  onUpdate,
}: {
  node: DRDNode;
  onUpdate: (id: string, updates: Partial<DRDNode>) => void;
}) {
  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-xs">URL</Label>
        <div className="flex gap-1">
          <Input
            className="h-8 text-xs flex-1"
            placeholder="https://..."
            value={node.url ?? ""}
            onChange={(e) => onUpdate(node.id, { url: e.target.value })}
          />
          {node.url && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              asChild
            >
              <a href={node.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs">Description</Label>
        <Textarea
          className="min-h-[60px] text-xs resize-none"
          placeholder="Describe this knowledge source..."
          value={node.description ?? ""}
          onChange={(e) => onUpdate(node.id, { description: e.target.value })}
        />
      </div>
    </>
  );
}
