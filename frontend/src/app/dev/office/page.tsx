"use client";

/**
 * The office on its own, replaying a scripted build — every department, every
 * engine, the pipeline from the first question to the handover, and Smith's
 * change afterwards. For showing the office and for checking it without a
 * backend: /dev/office
 */
import { useEffect, useRef, useState } from "react";
import { VirtualOffice } from "@/components/virtual-office";
import { useOfficeStore } from "@/components/virtual-office/OfficeStateManager";
import type { OfficeEvent } from "@/components/virtual-office/types";

type Beat = [number, OfficeEvent];

const S = (
  tool: string, kind: "read" | "try" | "write" | "ask" | "report" | "end" | "other", said: string, status = "read",
): OfficeEvent => ({ type: "smith_step", tool, kind, status, said });

const node = (agent: string, nodeKey: string, action: string, room = "discovery"): Beat[] => [
  [0, { type: "agent_start", agent, room, action, node: nodeKey }],
  [1800, { type: "agent_complete", agent, node: nodeKey }],
];

function script(): Beat[] {
  const beats: Beat[] = [];
  let t = 0;
  const at = (dt: number, e: OfficeEvent) => { t += dt; beats.push([t, e]); };
  const run = (seq: Beat[]) => { for (const [dt, e] of seq) at(dt, e); };

  // 1. The person comes to the Front Desk.
  at(400, { type: "smith_turn", status: "start", mode: "conversation", text: "Build me a bakery ordering app" });
  at(1500, S("open_decisions", "read", "Open decisions: the currency, who signs up, the colours"));
  at(1800, S("ask_user", "ask", "Which currency do you take, and may customers register themselves?"));
  at(1200, { type: "smith_turn", status: "end", mode: "conversation", outcome: "asked", text: "Which currency do you take?" });
  at(2500, { type: "smith_turn", status: "start", mode: "conversation", text: "GBP, and yes — customers register" });
  at(1500, S("define_application", "write", "15 requirements in 5 areas", "resolved"));
  at(1500, { type: "smith_turn", status: "end", mode: "conversation", outcome: "resolved", text: "Here is what the app needs to do — 15 requirements. Lock them in?" });

  // 2. Define, then the model.
  at(1500, { type: "pipeline_stage", stage: "define", label: "Writing down what the application is for" });
  at(0, { type: "run_plan", agents: ["requirement"] });
  run(node("requirement", "requirements", "Writing down what this app is for"));
  at(1200, { type: "pipeline_stage", stage: "model", label: "Working out what the application is made of" });
  at(0, { type: "run_plan", agents: ["product_analysis", "solution_architecture", "data_model", "page_design", "security", "integration"] });
  run(node("product_analysis", "application_model", "Working out the product shape"));
  run(node("solution_architecture", "ux_architecture", "Mapping modules and navigation", "architecture"));
  at(0, { type: "artifact_delivery", from: "solution_architecture", to: "data_model", artifact: "modules" });
  run(node("data_model", "entity_fields", "Detailing each entity's fields", "data"));
  at(600, { type: "agent_status", agent: "data_model", status: "Detailing each entity's fields (3/7)", subject: "ENTITY-003", node: "entity_fields" });
  run(node("page_design", "page_contracts", "Deciding the page set", "design_studio"));
  run(node("security", "security", "Setting roles and permissions", "security"));
  run(node("integration", "integrations", "Connecting the outside services", "architecture"));

  // 3. The engineer's build: the opening, then three features.
  at(1200, { type: "pipeline_stage", stage: "opening", label: "Finishing what comes before the first feature: install, design system, decisions" });
  at(0, { type: "run_plan", agents: ["build", "accessibility", "engineer", "ui_director"] });
  run(node("build", "install", "Installing the toolchain", "shipping"));
  run(node("accessibility", "design_system", "Setting the design language", "design_studio"));
  run(node("engineer", "decisions", "Deciding the facts every writer must agree on", "architecture"));
  at(800, { type: "pipeline_stage", stage: "build", label: "Building 3 features, each proven before the next",
            features: ["MODULE-001", "MODULE-002", "MODULE-003"], done: [] });

  const features: [string, string, string[]][] = [
    ["MODULE-001", "Menu", ["PAGE-001"]],
    ["MODULE-002", "Orders", ["PAGE-002", "PAGE-003"]],
    ["MODULE-003", "Baker Catalogue", ["PAGE-004"]],
  ];
  features.forEach(([id, name, pages], i) => {
    at(900, { type: "pipeline_stage", stage: "feature", label: `Building ${name}`, feature: id, name, index: i + 1, total: 3, pages });
    at(0, { type: "run_plan", agents: ["page_design", "workflow", "business_rules", "analytics", "testing", "page_template", "ui_director", "ui_engineer", "backend", "frontend", "build", "page_reviewer", "observer"] });
    run(node("page_design", "page_details", "Writing each feature's page contracts", "design_studio"));
    at(0, { type: "artifact_delivery", from: "page_design", to: "workflow", artifact: "pages" });
    run(node("workflow", "workflow_steps", "Authoring each workflow's steps", "logic"));
    if (i === 1) {
      at(300, { type: "agent_retry", agent: "workflow", attempt: 2, of: 2, reason: "FEEL: `=` not `==` in the guard" });
      at(1500, { type: "agent_complete", agent: "workflow", node: "workflow_steps" });
    }
    run(node("business_rules", "business_rules", "Writing the business rules", "logic"));
    run(node("testing", "expectations", "Writing what must happen, to be tried as the person", "qa"));
    run(node("page_template", "page_layouts", "Laying out each page", "composition"));
    run(node("ui_engineer", "page_code", "Writing each page in React", "composition"));
    at(300, { type: "agent_start", agent: "page_reviewer", room: "qa", action: `Reviewing ${name}'s screens`, node: "page_code" });
    at(1400, { type: "agent_complete", agent: "page_reviewer", node: "page_code" });
    run(node("backend", "backend", "Projecting the data layer", "data"));
    run(node("frontend", "frontend", "Projecting the page schemas", "composition"));
    run(node("build", "assemble", "Assembling and starting the application", "shipping"));
    // Proof on the Workbench.
    at(600, { type: "engine", engine: "apps_db", state: "busy", detail: "preparing the app's database and seed" });
    at(1200, { type: "engine", engine: "apps_db", state: "on", detail: "tables and logins in place" });
    at(300, { type: "engine", engine: "workbench", state: "busy", detail: "building the app as it ships" });
    at(1800, { type: "engine", engine: "workbench", state: "on", detail: "served and signed in" });
    const says = [`A customer sees the ${name.toLowerCase()} with prices in GBP`, `The baker marks an item sold out and the customer no longer sees it`];
    says.forEach((text, k) => {
      at(900, { type: "trial", statement: `EXP-00${i * 2 + k + 1}`, says: text, verdict: "trying", who: k ? "Baker" : "Customer" });
      const fails = i === 1 && k === 1;
      at(2200, { type: "trial", statement: `EXP-00${i * 2 + k + 1}`, says: text, verdict: fails ? "failed" : "passed", who: k ? "Baker" : "Customer" });
    });
    if (i === 1) {
      at(600, { type: "pipeline_stage", stage: "fix", label: `${name}: 1 statement not holding — Smith is finding the cause`, feature: id, name, round: 1, ids: ["EXP-004"] });
      at(400, { type: "smith_turn", status: "start", mode: "unattended", text: "While building Orders, a statement did not hold: the sold-out item still shows" });
      at(1200, S("read_page_code", "read", "/menu reads items without the soldOut filter"));
      at(1800, S("try_expectation", "try", "EXP-004 does not hold — the item is still listed", "read"));
      at(1800, S("write_page_code", "write", "Changed /menu: items where soldOut is false", "resolved"));
      at(1600, S("try_expectation", "try", "EXP-004 holds — the baker's sold-out item is gone", "read"));
      at(900, S("done", "end", "Fixed the menu's filter", "resolved"));
      at(600, { type: "smith_turn", status: "end", mode: "unattended", outcome: "resolved", text: "Fixed the menu's sold-out filter" });
      at(800, { type: "trial", statement: "EXP-004", says: says[1], verdict: "trying", who: "Baker" });
      at(2000, { type: "trial", statement: "EXP-004", says: says[1], verdict: "passed", who: "Baker" });
    }
    at(500, { type: "engine", engine: "workbench", state: "off" });
    at(300, { type: "pipeline_stage", stage: "proof", label: `${name}: 2 of 2 statements hold`, feature: id, name, statements: 2, passed: 2, failing: [], done: true });
  });

  // 4. Sweep, the whole application, handover.
  at(1200, { type: "pipeline_stage", stage: "sweep", label: "Writing what no feature claimed", nodes: ["workflow_steps", "integration", "assemble"] });
  run(node("workflow", "workflow_steps", "Authoring each workflow's steps", "logic"));
  run(node("build", "assemble", "Assembling and starting the application", "shipping"));
  at(800, { type: "pipeline_stage", stage: "whole", label: "The whole application: 6 of 6 statements hold", statements: 6, passed: 6, failing: [] });
  at(0, { type: "engine", engine: "workbench", state: "busy", detail: "trying every statement once more" });
  at(2500, { type: "engine", engine: "workbench", state: "off" });
  at(300, { type: "pipeline_stage", stage: "handover", label: "Built, tried and handed over" });
  at(300, { type: "build_success", total_files: 6 });

  // 5. A change, after.
  at(6000, { type: "smith_turn", status: "start", mode: "conversation", text: "The order total is wrong when I add two of the same item" });
  at(1500, S("read_section", "read", "FLOW-004 Checkout: compute_subtotal sums unit price, not quantity × price"));
  at(1800, S("open_page", "try", "Added two croissants as the customer — the total shows £2.40, not £4.80", "read"));
  at(2000, S("write_workflow_steps", "write", "Changed compute_subtotal: quantity × unitPrice", "resolved"));
  at(1800, S("try_workflow", "try", "Checkout as the customer: £4.80", "read"));
  at(900, S("done", "end", "Fixed the subtotal", "resolved"));
  at(600, { type: "smith_turn", status: "end", mode: "conversation", outcome: "resolved", text: "Fixed: two croissants now total £4.80. Tried it as the customer." });
  return beats;
}

export default function OfficeDemoPage() {
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [playing, setPlaying] = useState(true);
  const timers = useRef<number[]>([]);

  const start = () => {
    for (const id of timers.current) window.clearTimeout(id);
    timers.current = [];
    useOfficeStore.getState().reset();
    useOfficeStore.getState().initialize();
    setEvents([]);
    for (const [t, e] of script()) {
      timers.current.push(window.setTimeout(() => setEvents((prev) => [...prev, e]), t));
    }
    setPlaying(true);
  };

  useEffect(() => {
    start();
    return () => { for (const id of timers.current) window.clearTimeout(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col bg-slate-950">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-800 text-slate-300 text-sm">
        <span className="font-semibold text-white">The office</span>
        <span className="text-slate-500">a scripted build, from the first question to a change after the handover</span>
        <button onClick={start} className="ml-auto px-2.5 py-1 rounded border border-slate-700 hover:bg-slate-800 text-xs">
          Replay
        </button>
        <span className="text-xs text-slate-500">{playing ? `${events.length} events` : ""}</span>
      </div>
      <div className="flex-1 min-h-0">
        <VirtualOffice events={events} isGenerating />
      </div>
    </div>
  );
}
