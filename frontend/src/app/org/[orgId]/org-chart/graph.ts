/**
 * The organisation chart as one tree: the organisation at the top, its
 * departments (and their sub-departments) under it, teams under departments,
 * people under teams; teams and people that belong to nothing hang off the
 * organisation so nothing floats unconnected. A person in several teams is
 * one box with a line from each team. Who reports to whom (`manager_id`) is
 * drawn over the tree as a dashed line from the person to their manager; it
 * does not move the boxes.
 */
import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";

export interface ChartPerson {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string | null;
  manager_id: string | null;
  team_ids?: string[];
}

export interface ChartTeam {
  id: string;
  name: string;
  description: string | null;
  people: ChartPerson[];
}

export interface ChartDepartment {
  id: string;
  name: string;
  description: string | null;
  teams: ChartTeam[];
  people: ChartPerson[];
  children?: ChartDepartment[];
}

export interface OrgChart {
  departments: ChartDepartment[];
  unassigned_teams: ChartTeam[];
  unassigned_people: ChartPerson[];
}

export interface ChartOrganisation {
  name: string;
  slug?: string;
}

export const NODE_WIDTH = 200;
export const ORG_HEIGHT = 56;
export const DEPT_HEIGHT = 50;
export const TEAM_HEIGHT = 44;
export const PERSON_HEIGHT = 40;
export const ROOT_ID = "org-root";

export function buildGraph(org: ChartOrganisation, chart: OrgChart): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const seen = new Set<string>();

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 60, nodesep: 30 });

  const add = (node: Node, height: number) => {
    if (seen.has(node.id)) return false;
    seen.add(node.id);
    g.setNode(node.id, { width: NODE_WIDTH, height });
    nodes.push(node);
    return true;
  };
  const link = (source: string, target: string) => {
    edges.push({ id: `e-${source}-${target}`, source, target, type: "smoothstep" });
  };

  const departments = countDepartments(chart.departments);
  add({
    id: ROOT_ID,
    type: "organization",
    position: { x: 0, y: 0 },
    data: { label: org.name, slug: org.slug ?? "", count: departments },
  }, ORG_HEIGHT);

  const person = (p: ChartPerson, parent: string) => {
    // One box per person however many teams list them; a line from each.
    const id = `person-${p.id}`;
    add({ id, type: "person", position: { x: 0, y: 0 },
          data: { label: `${p.first_name} ${p.last_name}`.trim() || p.email, title: p.title } }, PERSON_HEIGHT);
    if (!edges.some((e) => e.source === parent && e.target === id)) link(parent, id);
  };
  const team = (t: ChartTeam, parent: string) => {
    const id = `team-${t.id}`;
    if (!add({ id, type: "team", position: { x: 0, y: 0 }, data: { label: t.name, count: t.people.length } }, TEAM_HEIGHT)) return;
    link(parent, id);
    for (const p of t.people) person(p, id);
  };
  const department = (d: ChartDepartment, parent: string) => {
    const id = `dept-${d.id}`;
    if (!add({ id, type: "department", position: { x: 0, y: 0 }, data: { label: d.name, count: d.teams.length } }, DEPT_HEIGHT)) return;
    link(parent, id);
    for (const child of d.children ?? []) department(child, id);
    for (const t of d.teams) team(t, id);
    for (const p of d.people) person(p, id);
  };

  for (const d of chart.departments) department(d, ROOT_ID);
  for (const t of chart.unassigned_teams) team(t, ROOT_ID);
  for (const p of chart.unassigned_people) person(p, ROOT_ID);

  for (const edge of edges) g.setEdge(edge.source, edge.target);
  dagre.layout(g);
  for (const node of nodes) {
    const laid = g.node(node.id);
    if (laid) node.position = { x: laid.x - NODE_WIDTH / 2, y: laid.y - (laid.height || 40) / 2 };
  }

  // Reporting lines, after the layout so they never pull a box out of its place.
  for (const p of everyPerson(chart)) {
    if (!p.manager_id || p.manager_id === p.id) continue;
    const from = `person-${p.id}`, to = `person-${p.manager_id}`;
    if (!seen.has(from) || !seen.has(to)) continue;
    const id = `reports-${p.id}`;
    if (edges.some((e) => e.id === id)) continue;
    edges.push({
      id, source: to, target: from, type: "default", label: "reports to",
      style: { strokeDasharray: "6 4", stroke: "hsl(var(--primary))", strokeWidth: 1.25 },
      labelStyle: { fontSize: 9, fill: "hsl(var(--muted-foreground))" },
      labelBgStyle: { fill: "hsl(var(--background))" },
      data: { reporting: true },
    });
  }
  return { nodes, edges };
}

/** Every person in the chart, however many teams list them, each once. */
export function everyPerson(chart: OrgChart): ChartPerson[] {
  const out = new Map<string, ChartPerson>();
  const take = (p: ChartPerson) => { if (!out.has(p.id)) out.set(p.id, p); };
  const dept = (d: ChartDepartment) => {
    d.people.forEach(take);
    d.teams.forEach((t) => t.people.forEach(take));
    (d.children ?? []).forEach(dept);
  };
  chart.departments.forEach(dept);
  chart.unassigned_teams.forEach((t) => t.people.forEach(take));
  chart.unassigned_people.forEach(take);
  return [...out.values()];
}

function countDepartments(list: ChartDepartment[]): number {
  return list.reduce((n, d) => n + 1 + countDepartments(d.children ?? []), 0);
}
