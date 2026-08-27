"use client";

import { useMemo, useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  MarkerType,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Plus, Maximize } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EntityCardNode, type EntityCardData } from "./EntityCardNode";
import { layoutTables } from "./erd-layout";
import type { AppModel } from "@/types/app-model";

const nodeTypes: NodeTypes = {
  entityCard: EntityCardNode as unknown as NodeTypes[string],
};

const EDGE_LABEL_MAP: Record<string, string> = {
  "one-to-one": "1:1",
  "one-to-many": "1:N",
  "many-to-many": "N:M",
};

interface ERDCanvasProps {
  appModel: AppModel;
  onAddModel?: () => void;
  onAddField?: (tableName: string) => void;
  onEditField?: (tableName: string, columnName: string) => void;
  onDeleteModel?: (tableName: string) => void;
  onAddIndex?: (tableName: string) => void;
  onAddRelation?: (tableName: string) => void;
  onSelectTable?: (tableName: string) => void;
}

export function ERDCanvas({
  appModel,
  onAddModel,
  onAddField,
  onEditField,
  onDeleteModel,
  onAddIndex,
  onAddRelation,
  onSelectTable,
}: ERDCanvasProps) {
  const tables = appModel.database?.tables ?? [];

  const { initialNodes, initialEdges } = useMemo(() => {
    const positions = layoutTables(tables);
    const posMap = new Map(positions.map((p) => [p.id, { x: p.x, y: p.y }]));

    const nodes: Node<EntityCardData>[] = tables.map((table) => ({
      id: table.name,
      type: "entityCard",
      position: posMap.get(table.name) || { x: 0, y: 0 },
      data: {
        label: table.name,
        columns: table.columns,
        relations: table.relations,
        onAddField,
        onEditField,
        onDeleteModel,
        onAddIndex,
        onAddRelation,
        onSelectTable,
      },
    }));

    const edges: Edge[] = [];
    const edgeSet = new Set<string>();

    for (const table of tables) {
      // From relations array
      for (const rel of table.relations ?? []) {
        const edgeId = `${table.name}-${rel.target}-${rel.foreignKey}`;
        if (!edgeSet.has(edgeId)) {
          edgeSet.add(edgeId);
          edges.push({
            id: edgeId,
            source: table.name,
            target: rel.target,
            label: EDGE_LABEL_MAP[rel.type] || rel.type,
            type: "smoothstep",
            animated: rel.type === "many-to-many",
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: "#94a3b8", strokeWidth: 1.5 },
            labelStyle: { fontSize: 10, fill: "#64748b" },
          });
        }
      }

      // From column references
      for (const col of table.columns) {
        if (col.references) {
          const edgeId = `${table.name}-${col.references.table}-${col.name}`;
          if (!edgeSet.has(edgeId)) {
            edgeSet.add(edgeId);
            edges.push({
              id: edgeId,
              source: table.name,
              target: col.references.table,
              label: "FK",
              type: "smoothstep",
              markerEnd: { type: MarkerType.ArrowClosed },
              style: { stroke: "#94a3b8", strokeWidth: 1.5 },
              labelStyle: { fontSize: 10, fill: "#64748b" },
            });
          }
        }
      }
    }

    return { initialNodes: nodes, initialEdges: edges };
  }, [tables, onAddField, onEditField, onDeleteModel, onAddIndex, onAddRelation, onSelectTable]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes/edges when the upstream app model actually changes. We can't
  // depend on `initialNodes`/`initialEdges` directly — those are useMemo
  // results whose identity flips every render that the parent's callback
  // props are not memoised, which would re-fire this effect infinitely. Use
  // a stable JSON hash of the source `tables` instead, which only changes
  // when the data structurally changes.
  const tablesHash = useMemo(() => JSON.stringify(tables), [tables]);
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
    // initialNodes/initialEdges are intentionally NOT in deps — see above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tablesHash, setNodes, setEdges]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="#f1f5f9" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor="#e2e8f0"
          maskColor="rgba(0,0,0,0.08)"
          className="!bottom-4 !right-4"
        />
        <Panel position="top-right" className="flex gap-2">
          {onAddModel && (
            <Button size="sm" variant="outline" onClick={onAddModel}>
              <Plus className="mr-1 h-3 w-3" />
              Add Model
            </Button>
          )}
        </Panel>
      </ReactFlow>
    </div>
  );
}
