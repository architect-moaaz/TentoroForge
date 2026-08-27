"use client";

import { use, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "dagre";
import { Building2, Users, User } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";

import "@xyflow/react/dist/style.css";

interface ChartPerson {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string | null;
  manager_id: string | null;
}

interface ChartTeam {
  id: string;
  name: string;
  description: string | null;
  people: ChartPerson[];
}

interface ChartDepartment {
  id: string;
  name: string;
  description: string | null;
  teams: ChartTeam[];
  people: ChartPerson[];
}

interface OrgChart {
  departments: ChartDepartment[];
  unassigned_teams: ChartTeam[];
  unassigned_people: ChartPerson[];
}

const NODE_WIDTH = 200;
const DEPT_HEIGHT = 50;
const TEAM_HEIGHT = 44;
const PERSON_HEIGHT = 40;

function DepartmentNode({ data }: { data: { label: string; count: number } }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border-2 border-primary/40 bg-primary/5 px-4 py-3 shadow-sm">
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

function PersonNode({
  data,
}: {
  data: { label: string; title: string | null };
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 shadow-sm">
      <User className="h-4 w-4 text-muted-foreground" />
      <div>
        <p className="text-xs font-medium">{data.label}</p>
        {data.title && (
          <p className="text-[10px] text-muted-foreground">{data.title}</p>
        )}
      </div>
    </div>
  );
}

const nodeTypes = {
  department: DepartmentNode,
  team: TeamNode,
  person: PersonNode,
};

function buildGraph(chart: OrgChart): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 60, nodesep: 30 });

  // Add department nodes
  for (const dept of chart.departments) {
    const nodeId = `dept-${dept.id}`;
    g.setNode(nodeId, { width: NODE_WIDTH, height: DEPT_HEIGHT });
    nodes.push({
      id: nodeId,
      type: "department",
      position: { x: 0, y: 0 },
      data: { label: dept.name, count: dept.teams.length },
    });

    // Add teams within this department
    for (const team of dept.teams) {
      const teamNodeId = `team-${team.id}`;
      g.setNode(teamNodeId, { width: NODE_WIDTH, height: TEAM_HEIGHT });
      nodes.push({
        id: teamNodeId,
        type: "team",
        position: { x: 0, y: 0 },
        data: { label: team.name, count: team.people.length },
      });
      edges.push({
        id: `e-${nodeId}-${teamNodeId}`,
        source: nodeId,
        target: teamNodeId,
        type: "smoothstep",
      });

      // Add people within this team
      for (const person of team.people) {
        const personNodeId = `person-${person.id}`;
        g.setNode(personNodeId, { width: NODE_WIDTH, height: PERSON_HEIGHT });
        nodes.push({
          id: personNodeId,
          type: "person",
          position: { x: 0, y: 0 },
          data: {
            label: `${person.first_name} ${person.last_name}`,
            title: person.title,
          },
        });
        edges.push({
          id: `e-${teamNodeId}-${personNodeId}`,
          source: teamNodeId,
          target: personNodeId,
          type: "smoothstep",
        });
      }
    }

    // Unassigned people in department (no team)
    for (const person of dept.people) {
      const personNodeId = `person-${person.id}`;
      g.setNode(personNodeId, { width: NODE_WIDTH, height: PERSON_HEIGHT });
      nodes.push({
        id: personNodeId,
        type: "person",
        position: { x: 0, y: 0 },
        data: {
          label: `${person.first_name} ${person.last_name}`,
          title: person.title,
        },
      });
      edges.push({
        id: `e-${nodeId}-${personNodeId}`,
        source: nodeId,
        target: personNodeId,
        type: "smoothstep",
      });
    }
  }

  // Unassigned teams (no department)
  for (const team of chart.unassigned_teams) {
    const teamNodeId = `team-${team.id}`;
    g.setNode(teamNodeId, { width: NODE_WIDTH, height: TEAM_HEIGHT });
    nodes.push({
      id: teamNodeId,
      type: "team",
      position: { x: 0, y: 0 },
      data: { label: team.name, count: team.people.length },
    });

    for (const person of team.people) {
      const personNodeId = `person-${person.id}`;
      g.setNode(personNodeId, { width: NODE_WIDTH, height: PERSON_HEIGHT });
      nodes.push({
        id: personNodeId,
        type: "person",
        position: { x: 0, y: 0 },
        data: {
          label: `${person.first_name} ${person.last_name}`,
          title: person.title,
        },
      });
      edges.push({
        id: `e-${teamNodeId}-${personNodeId}`,
        source: teamNodeId,
        target: personNodeId,
        type: "smoothstep",
      });
    }
  }

  // Unassigned people (no department, no team)
  for (const person of chart.unassigned_people) {
    const personNodeId = `person-${person.id}`;
    g.setNode(personNodeId, { width: NODE_WIDTH, height: PERSON_HEIGHT });
    nodes.push({
      id: personNodeId,
      type: "person",
      position: { x: 0, y: 0 },
      data: {
        label: `${person.first_name} ${person.last_name}`,
        title: person.title,
      },
    });
  }

  // Add edges to dagre
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  // Run layout
  dagre.layout(g);

  // Apply positions
  for (const node of nodes) {
    const dagreNode = g.node(node.id);
    if (dagreNode) {
      node.position = {
        x: dagreNode.x - NODE_WIDTH / 2,
        y: dagreNode.y - (dagreNode.height || 40) / 2,
      };
    }
  }

  return { nodes, edges };
}

function OrgChartFlow({ orgId }: { orgId: string }) {
  const { data: chart } = useQuery({
    queryKey: ["org", orgId, "org-chart"],
    queryFn: () => api.get<OrgChart>(`/api/orgs/${orgId}/org-chart`),
  });

  const { initialNodes, initialEdges } = useMemo(() => {
    if (!chart)
      return { initialNodes: [] as Node[], initialEdges: [] as Edge[] };
    const { nodes, edges } = buildGraph(chart);
    return { initialNodes: nodes, initialEdges: edges };
  }, [chart]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

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
