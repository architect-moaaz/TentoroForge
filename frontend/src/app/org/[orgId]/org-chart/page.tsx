"use client";

import { use, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import { Building, Building2, Users, User } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { buildGraph, type OrgChart } from "./graph";

import "@xyflow/react/dist/style.css";

// EVERY NODE HAS A HANDLE AT ITS TOP AND ITS BOTTOM. React Flow attaches an
// edge to a handle; a custom node without them draws no edges at all, which is
// how the chart showed its boxes with no lines between them.
const HANDLE = "!h-1.5 !w-1.5 !min-h-0 !min-w-0 !border-0 !bg-transparent";
function Ports() {
  return (
    <>
      <Handle type="target" position={Position.Top} className={HANDLE} />
      <Handle type="source" position={Position.Bottom} className={HANDLE} />
    </>
  );
}

function OrganizationNode({ data }: { data: { label: string; slug: string; count: number } }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border-2 border-primary bg-primary px-4 py-3 text-primary-foreground shadow-md">
      <Ports />
      <Building className="h-5 w-5" />
      <div>
        <p className="text-sm font-semibold">{data.label}</p>
        <p className="text-xs opacity-80">
          {data.slug ? `/${data.slug} · ` : ""}{data.count} department{data.count !== 1 ? "s" : ""}
        </p>
      </div>
    </div>
  );
}

function DepartmentNode({ data }: { data: { label: string; count: number } }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border-2 border-primary/40 bg-primary/5 px-4 py-3 shadow-sm">
      <Ports />
      <Building2 className="h-5 w-5 text-primary" />
      <div>
        <p className="text-sm font-semibold">{data.label}</p>
        <p className="text-xs text-muted-foreground">
          {data.count} team{data.count !== 1 ? "s" : ""}
        </p>
      </div>
    </div>
  );
}

function TeamNode({ data }: { data: { label: string; count: number } }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 shadow-sm dark:border-blue-700 dark:bg-blue-950">
      <Ports />
      <Users className="h-4 w-4 text-blue-600 dark:text-blue-400" />
      <div>
        <p className="text-sm font-medium">{data.label}</p>
        <p className="text-xs text-muted-foreground">
          {data.count} member{data.count !== 1 ? "s" : ""}
        </p>
      </div>
    </div>
  );
}

function PersonNode({ data }: { data: { label: string; title: string | null } }) {
  return (
    <div className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 shadow-sm">
      <Ports />
      <User className="h-4 w-4 text-muted-foreground" />
      <div>
        <p className="text-xs font-medium">{data.label}</p>
        {data.title && <p className="text-[10px] text-muted-foreground">{data.title}</p>}
      </div>
    </div>
  );
}

const nodeTypes = {
  organization: OrganizationNode,
  department: DepartmentNode,
  team: TeamNode,
  person: PersonNode,
};

function OrgChartFlow({ orgId }: { orgId: string }) {
  const { data: chart } = useQuery({
    queryKey: ["org", orgId, "org-chart"],
    queryFn: () => api.get<OrgChart>(`/api/orgs/${orgId}/org-chart`),
  });
  // The organisation itself heads the chart; the layout already holds it.
  const { data: org } = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => api.get<{ name: string; slug: string }>(`/api/orgs/${orgId}`),
  });

  const { initialNodes, initialEdges } = useMemo(() => {
    if (!chart)
      return { initialNodes: [] as Node[], initialEdges: [] as Edge[] };
    const { nodes, edges } = buildGraph({ name: org?.name ?? "Organisation", slug: org?.slug }, chart);
    return { initialNodes: nodes, initialEdges: edges };
  }, [chart, org?.name, org?.slug]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  // The chart arrives after the first render; the state was seeded empty.
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  if (!chart) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  const isEmpty =
    chart.departments.length === 0 &&
    chart.unassigned_teams.length === 0 &&
    chart.unassigned_people.length === 0;

  if (isEmpty) {
    return (
      <div className="p-8">
        <h1 className="mb-6 text-2xl font-semibold text-foreground">Organization Chart</h1>
        <Card className="border-dashed">
          <CardHeader className="items-center text-center">
            <CardTitle>Empty org chart</CardTitle>
            <p className="text-sm text-muted-foreground">
              Add departments, teams, and people to see the org chart
            </p>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="p-8 pb-0">
        <h1 className="mb-4 text-2xl font-semibold text-foreground">Organization Chart</h1>
      </div>
      <div className="flex-1" style={{ minHeight: "600px" }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          // A COLOUR TOKEN IS USED AS IT IS. Wrapping --primary in hsl() parsed, but
          // the app's --primary is an oklch colour, so the value failed at computed
          // time and `stroke` fell to its initial `none`: eight edges drawn, none
          // visible. Opacity goes on its own property.
          defaultEdgeOptions={{ type: "smoothstep", style: { stroke: "var(--primary)", strokeOpacity: 0.45, strokeWidth: 1.5 } }}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Controls showInteractive={false} />
          <MiniMap
            nodeStrokeWidth={3}
            zoomable
            pannable
            className="rounded-md border"
          />
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        </ReactFlow>
      </div>
    </div>
  );
}

export default function OrgChartPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <OrgChartFlow orgId={orgId} />;
}
