/**
 * The app's flows as the App Flow view draws them — the shape
 * `GET /api/projects/{id}/flows` returns (`app_flows.graph`), and the same
 * shape read straight off a Blueprint document, for a panel that already
 * holds one (Smith's side panel at approval, before any build).
 */

export type FlowNode = {
  id: string; page: string; screen: string; route: string; part: string; placement: string; last: boolean;
  does?: string; process?: string;
};
export type FlowEdge = { from: string; to: string; does: string; process: string; then: "go" | "offer" | "menu" };
export type Flow = { id: string; name: string; role: string; goal: string; ends: string; nodes: FlowNode[]; edges: FlowEdge[] };
export type FlowsResponse = { flows: Flow[]; findings: string[] };

type Row = Record<string, any>;
const live = (rows: unknown): Row[] =>
  Array.isArray(rows) ? rows.filter((r) => r && typeof r === "object" && !["DEPRECATED", "SUPERSEDED"].includes(r.status)) : [];

/** `app_flows.graph`, in the browser. */
export function flowsFromDoc(doc: Record<string, unknown> | null | undefined): Flow[] {
  if (!doc) return [];
  const pages = new Map(live(doc.pages).map((p) => [String(p.id), p]));
  const roles = new Map(live(doc.roles).map((r) => [String(r.id), String(r.name ?? "")]));
  const processes = new Map(live(doc.workflows).map((w) => [String(w.id), String(w.name ?? "")]));
  return live(doc.flows).filter((f) => Array.isArray(f.steps)).map((f) => {
    const steps: Row[] = f.steps;
    const nodes: FlowNode[] = steps.map((st, i) => {
      const page = pages.get(String(st.page)) ?? {};
      const sec = (page.sections ?? []).find((s: Row) => s && String(s.key) === String(st.section ?? ""));
      const last = i === steps.length - 1;
      return {
        id: `s${i}`, page: String(st.page), screen: String(page.name ?? st.page), route: String(page.route ?? ""),
        part: sec ? String(sec.label ?? sec.key) : "", placement: sec ? String(sec.placement ?? "") : "", last,
        ...(last && (st.does || st.workflow)
          ? { does: String(st.does ?? ""), process: processes.get(String(st.workflow ?? "")) ?? "" } : {}),
      };
    });
    const edges: FlowEdge[] = steps.slice(1).map((_, i) => ({
      from: `s${i}`, to: `s${i + 1}`, does: String(steps[i].does ?? ""),
      process: processes.get(String(steps[i].workflow ?? "")) ?? "", then: (steps[i].then ?? "go") as FlowEdge["then"],
    }));
    return { id: String(f.id), name: String(f.name ?? ""), role: roles.get(String(f.role ?? "")) ?? "",
             goal: String(f.goal ?? ""), ends: String(f.ends ?? ""), nodes, edges };
  });
}
