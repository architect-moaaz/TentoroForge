/**
 * The organisation chart showed boxes with no lines between them and no
 * organisation at the top. The graph is one tree from the organisation down,
 * and every node carries the handles an edge needs to attach.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ROOT_ID, buildGraph, type OrgChart } from "@/app/org/[orgId]/org-chart/graph";

const person = (id: string, first: string, title: string | null = null, manager_id: string | null = null) =>
  ({ id, email: `${first.toLowerCase()}@example.com`, first_name: first, last_name: "Shareef", title, manager_id });

const mo = person("mo", "Moaaz", "Director of Technology");
const chart: OrgChart = {
  departments: [
    { id: "eng", name: "Engineering", description: null, people: [],
      // Moaaz is in Forge and in Genesys: one box, a line from each team.
      teams: [{ id: "forge", name: "Forge", description: null, people: [mo] },
              { id: "genesys", name: "Genesys", description: null, people: [mo] }],
      children: [{ id: "qa", name: "QA", description: null, teams: [], people: [person("ann", "Ann", null, "mo")] }] },
    { id: "sales", name: "Sales & Marketing", description: null, teams: [], people: [] },
  ],
  unassigned_teams: [{ id: "ops", name: "Ops", description: null, people: [] }],
  unassigned_people: [person("zed", "Zed")],
};

describe("the organisation chart", () => {
  const { nodes, edges } = buildGraph({ name: "Tentoro-IND", slug: "tentoro-ind" }, chart);
  const edge = (source: string, target: string) => edges.some((e) => e.source === source && e.target === target);

  it("starts from the organisation", () => {
    const root = nodes.find((n) => n.id === ROOT_ID);
    expect(root?.type).toBe("organization");
    expect(root?.data).toMatchObject({ label: "Tentoro-IND", slug: "tentoro-ind", count: 3 });
    expect(edge(ROOT_ID, "dept-eng") && edge(ROOT_ID, "dept-sales")).toBe(true);
  });

  it("connects every box to the one it belongs to, and the strays to the organisation", () => {
    expect(edge("dept-eng", "team-forge") && edge("dept-eng", "team-genesys")).toBe(true);
    expect(edge("team-forge", "person-mo") && edge("team-genesys", "person-mo")).toBe(true);
    expect(nodes.filter((n) => n.id === "person-mo")).toHaveLength(1);
    expect(edge("dept-eng", "dept-qa") && edge("dept-qa", "person-ann")).toBe(true);
    expect(edge(ROOT_ID, "team-ops") && edge(ROOT_ID, "person-zed")).toBe(true);
    // Nothing floats: every node but the root hangs from at least one box.
    const tree = edges.filter((e) => !e.data?.reporting);
    for (const n of nodes) {
      if (n.id === ROOT_ID) continue;
      expect(tree.filter((e) => e.target === n.id).length, n.id).toBeGreaterThanOrEqual(1);
    }
  });

  it("draws who reports to whom as a dashed line that does not move the boxes", () => {
    const line = edges.find((e) => e.id === "reports-ann");
    expect(line).toMatchObject({ source: "person-mo", target: "person-ann", label: "reports to", data: { reporting: true } });
    expect(String(line?.style?.strokeDasharray)).toBe("6 4");
    // Only people with a manager get one; a manager outside the chart draws nothing.
    expect(edges.filter((e) => e.data?.reporting)).toHaveLength(1);
    const alone = buildGraph({ name: "X" }, { departments: [], unassigned_teams: [], unassigned_people: [person("solo", "Solo", null, "ghost")] });
    expect(alone.edges.filter((e) => e.data?.reporting)).toHaveLength(0);
    // The layout placed the organisation above its departments.
    const y = (id: string) => nodes.find((n) => n.id === id)!.position.y;
    expect(y(ROOT_ID)).toBeLessThan(y("dept-eng"));
    expect(y("dept-eng")).toBeLessThan(y("team-forge"));
  });

  it("gives every node the handles an edge attaches to", () => {
    const page = readFileSync(resolve(process.cwd(), "src/app/org/[orgId]/org-chart/page.tsx"), "utf8");
    expect(page).toContain('<Handle type="target" position={Position.Top}');
    expect(page).toContain('<Handle type="source" position={Position.Bottom}');
    for (const node of ["OrganizationNode", "DepartmentNode", "TeamNode", "PersonNode"]) {
      const body = page.slice(page.indexOf(`function ${node}(`), page.indexOf("const nodeTypes"));
      expect(body.indexOf("<Ports />"), node).toBeGreaterThan(-1);
    }
  });
});
