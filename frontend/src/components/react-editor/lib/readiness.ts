/**
 * The publish readiness check (UX-011): what would embarrass the page, found
 * on the model rather than in compiler output, and said plainly. Compiler
 * findings from the server join as "must fix".
 */
import type { Finding, ModelNode, PageDoc, PageModel } from "../types";
import { plainName } from "./plain";

export interface ReadinessGroups {
  mustFix: Finding[];
  recommended: Finding[];
  ready: string[];
}

const PLACEHOLDERS = [/^new heading$/i, /^some text$/i, /^button$/i, /^card title$/i, /^heading$/i,
                      /^describe the picture$/i, /placehold\.co/i, /^label$/i, /^type here$/i, /^open page$/i,
                      /lorem ipsum/i];

function routeMatches(href: string, routes: string[]): boolean {
  const path = href.split("?")[0];
  return routes.some((r) => {
    const re = new RegExp("^" + r.replace(/\[[^\]]+\]/g, "[^/]+").replace(/\//g, "\\/") + "\\/?$");
    return re.test(path);
  });
}

export function checkModel(doc: PageDoc): Finding[] {
  const model = doc.model;
  if (!model) return [];
  const out: Finding[] = [];
  const routes = doc.pages.map((p) => p.route);
  const view = doc.source?.view ?? "";
  const nodes = Object.values(model.nodes);
  const f = (node: ModelNode | null, plain: string, severity: Finding["severity"], code: string): Finding => ({
    file: "view.tsx", line: node?.line ?? null, code, raw: plain, plain, severity, nodeId: node?.id,
  });

  for (const node of nodes) {
    const name = plainName(node, doc.registry);
    const href = node.props.find((p) => p.name === "href");
    if (href && href.kind === "string" && href.value?.startsWith("/") && !routeMatches(href.value, routes)) {
      out.push(f(node, `${name} opens “${href.value}”, which is not a page of this app.`, "must-fix", "broken-link"));
    }
    if (node.type === "img" || node.type === "Image") {
      const alt = node.props.find((p) => p.name === "alt");
      if (!alt || (alt.kind === "string" && !alt.value?.trim())) {
        out.push(f(node, `${name} has no description for people who cannot see it.`, "must-fix", "no-alt"));
      }
    }
    if ((node.type === "Button" || node.type === "button") && !node.context) {
      const hasAction = node.props.some((p) => ["onClick", "asChild", "type", "form", "href"].includes(p.name))
        || node.children.some((c) => ["Link", "a"].includes(model.nodes[c]?.type));
      if (!hasAction) out.push(f(node, `${name} does nothing when pressed — choose what happens when it is clicked.`, "recommended", "idle-button"));
    }
    if (node.type === "Input" || node.type === "input" || node.type === "Textarea" || node.type === "textarea") {
      const id = node.props.find((p) => p.name === "id" && p.kind === "string")?.value;
      const labelled = node.props.some((p) => p.name === "aria-label" || p.name === "aria-labelledby")
        || (id && nodes.some((n) => (n.type === "Label" || n.type === "label")
            && n.props.some((p) => p.name === "htmlFor" && p.value === id)));
      if (!labelled) out.push(f(node, `${name} has no label, so people will not know what to type.`, "must-fix", "no-label"));
    }
    if (node.kind === "element" && ["div", "section"].includes(node.type) && !node.children.length
        && !(node.text ?? "").trim() && !node.props.some((p) => p.name === "aria-hidden")) {
      out.push(f(node, `An empty ${name.toLowerCase()} — add something to it or remove it.`, "recommended", "empty"));
    }
    const text = node.textEditable ? (node.text ?? "") : "";
    const strings = [text, ...node.props.filter((p) => p.kind === "string").map((p) => p.value ?? "")];
    if (strings.some((s) => PLACEHOLDERS.some((re) => re.test(s.trim())))) {
      out.push(f(node, `${name} still shows placeholder text.`, "recommended", "placeholder"));
    }
  }

  for (const wf of doc.workflows) {
    if (!wf.launchedFrom.includes(doc.page.id) || !wf.key) continue;
    if (!new RegExp(`\\bworkflows\\.${wf.key}\\b`).test(view)) {
      out.push(f(null, `Nothing on this page lets people “${wf.name}”, which this page is meant to offer.`, "must-fix", "unwired-workflow"));
    }
  }
  return out;
}

export function groupFindings(doc: PageDoc, serverFindings: Finding[]): ReadinessGroups {
  const own = checkModel(doc);
  const all = [...serverFindings.map((s) => ({ ...s, severity: "must-fix" as const })), ...own];
  const mustFix = all.filter((x) => x.severity === "must-fix");
  const recommended = all.filter((x) => x.severity === "recommended");
  const ready: string[] = [];
  if (!serverFindings.length) ready.push("The page compiles against the app's data, workflows and pages.");
  if (!own.some((x) => x.code === "broken-link")) ready.push("Every link opens a page that exists.");
  if (!own.some((x) => x.code === "no-label" || x.code === "no-alt")) ready.push("Fields and images are labelled for screen readers.");
  if (!own.some((x) => x.code === "unwired-workflow")) ready.push("Everything this page is meant to do has a control.");
  return { mustFix, recommended, ready };
}

/** The layer tree's per-node marks: a finding on the node or one of its descendants. */
export function findingsByNode(model: PageModel, findings: Finding[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const x of findings) {
    if (!x.nodeId) continue;
    let cur: ModelNode | undefined = model.nodes[x.nodeId];
    while (cur) {
      out[cur.id] = (out[cur.id] ?? 0) + 1;
      cur = cur.parent ? model.nodes[cur.parent] : undefined;
    }
  }
  return out;
}
