"use client";

import { memo } from "react";
import { isBranchingNode } from "../branching";
import type { CSSProperties } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Zap,
  Play,
  GitBranch,
  Clock,
  Square,
  UserPlus,
  CheckCircle,
  Users,
  ArrowUpCircle,
  Brain,
  ScanText,
  Sparkles,
  Table2,
  Hand,
  Webhook,
  Calendar,
  Database,
  Globe,
  Mail,
  Bell,
  Split,
  GitMerge,
  Hash,
  FileText,
  Plug,
} from "lucide-react";
import type { WorkflowNodeData, WorkflowNodeType } from "@/types/workflow";

// ---------------------------------------------------------------------------
// Icon lookup
// ---------------------------------------------------------------------------
const ICONS: Record<string, typeof Zap> = {
  Zap, Play, GitBranch, Clock, Square, UserPlus, CheckCircle, Users,
  ArrowUpCircle, Brain, ScanText, Sparkles, Table2, Hand, Webhook,
  Calendar, Database, Globe, Mail, Bell, Split, GitMerge, Hash, FileText, Plug,
};

// ---------------------------------------------------------------------------
// Gradient + icon mapping — keyed by "nodeType" or "nodeType:subType"
// Each variant gets its own unique gradient color.
// ---------------------------------------------------------------------------
interface NodeVisual {
  gradient: string;
  icon: typeof Zap;
}

const NODE_VISUALS: Record<string, NodeVisual> = {
  // Triggers (keyed by trigger config.type)
  "trigger:manual":    { gradient: "bg-gradient-to-br from-orange-400 to-orange-600", icon: Hand },
  "trigger:webhook":   { gradient: "bg-gradient-to-br from-purple-400 to-purple-600", icon: Webhook },
  "trigger:schedule":  { gradient: "bg-gradient-to-br from-sky-400 to-sky-600",       icon: Calendar },
  "trigger:api_event": { gradient: "bg-gradient-to-br from-rose-400 to-rose-600",     icon: Zap },
  "trigger:db_change": { gradient: "bg-gradient-to-br from-amber-400 to-amber-600",   icon: Database },
  // fallback trigger
  trigger:             { gradient: "bg-gradient-to-br from-orange-400 to-orange-600",  icon: Zap },

  // Actions (keyed by config.actionType)
  "action:custom":            { gradient: "bg-gradient-to-br from-teal-400 to-teal-600",    icon: Play },
  "action:db_query":          { gradient: "bg-gradient-to-br from-cyan-400 to-cyan-600",    icon: Database },
  "action:http_call":         { gradient: "bg-gradient-to-br from-indigo-400 to-indigo-600", icon: Globe },
  "action:send_email":        { gradient: "bg-gradient-to-br from-blue-400 to-blue-600",    icon: Mail },
  "action:send_notification": { gradient: "bg-gradient-to-br from-orange-400 to-amber-500", icon: Bell },
  "action:db_insert":         { gradient: "bg-gradient-to-br from-green-400 to-green-600",  icon: Database },
  "action:db_update":         { gradient: "bg-gradient-to-br from-lime-400 to-lime-600",    icon: Database },
  "action:db_delete":         { gradient: "bg-gradient-to-br from-red-400 to-rose-600",     icon: Database },
  "action:set_variable":      { gradient: "bg-gradient-to-br from-slate-400 to-slate-600",  icon: Hash },
  "action:transform":         { gradient: "bg-gradient-to-br from-stone-400 to-stone-600",  icon: Hash },
  "action:generate_document": { gradient: "bg-gradient-to-br from-emerald-400 to-teal-600", icon: FileText },
  "action:mcp_tool_call":     { gradient: "bg-gradient-to-br from-violet-400 to-indigo-600",  icon: Plug },
  mcp_tool_call:              { gradient: "bg-gradient-to-br from-violet-400 to-indigo-600",  icon: Plug },
  // fallback action
  action:                     { gradient: "bg-gradient-to-br from-teal-400 to-teal-600",    icon: Play },

  // Flow control
  condition: { gradient: "bg-gradient-to-br from-purple-500 to-purple-700",  icon: GitBranch },
  decision:  { gradient: "bg-gradient-to-br from-emerald-500 to-green-700",  icon: Table2 },
  wait:      { gradient: "bg-gradient-to-br from-amber-500 to-amber-700",    icon: Clock },
  end:       { gradient: "bg-gradient-to-br from-red-400 to-red-600",        icon: Square },
  end_event: { gradient: "bg-gradient-to-br from-red-400 to-red-600",        icon: Square },

  // Gateways / parallel flow
  exclusive_gateway: { gradient: "bg-gradient-to-br from-purple-500 to-fuchsia-700", icon: GitBranch },
  parallel_gateway:  { gradient: "bg-gradient-to-br from-cyan-500 to-blue-700",      icon: Split },
  fork:              { gradient: "bg-gradient-to-br from-teal-500 to-cyan-700",      icon: Split },
  join:              { gradient: "bg-gradient-to-br from-blue-500 to-indigo-700",    icon: GitMerge },

  // Human-in-loop
  assignment: { gradient: "bg-gradient-to-br from-blue-500 to-blue-700",   icon: UserPlus },
  user_task:  { gradient: "bg-gradient-to-br from-blue-500 to-blue-700",   icon: UserPlus },
  approval:   { gradient: "bg-gradient-to-br from-indigo-500 to-indigo-700", icon: CheckCircle },
  task_pool:  { gradient: "bg-gradient-to-br from-sky-500 to-sky-700",     icon: Users },
  escalation: { gradient: "bg-gradient-to-br from-rose-500 to-rose-700",   icon: ArrowUpCircle },

  // AI nodes
  ai_classify: { gradient: "bg-gradient-to-br from-violet-500 to-violet-700",  icon: Brain },
  ai_extract:  { gradient: "bg-gradient-to-br from-fuchsia-500 to-fuchsia-700", icon: ScanText },
  ai_decide:   { gradient: "bg-gradient-to-br from-purple-500 to-violet-700",  icon: GitBranch },
  ai_generate: { gradient: "bg-gradient-to-br from-pink-500 to-pink-700",      icon: Sparkles },
};

function getVisual(nodeType: WorkflowNodeType, config: WorkflowNodeData["config"] | undefined): NodeVisual {
  // Try specific variant first
  if (nodeType === "trigger" && config?.type) {
    const key = `trigger:${config.type}`;
    if (NODE_VISUALS[key]) return NODE_VISUALS[key];
  }
  if (nodeType === "action" && config?.actionType) {
    const key = `action:${config.actionType}`;
    if (NODE_VISUALS[key]) return NODE_VISUALS[key];
    // Legacy form: an `action` node whose actionType is itself a node type (e.g.
    // ai_generate) — use that top-level visual so older workflows show the AI/etc.
    // icon, not the generic action fallback.
    if (NODE_VISUALS[config.actionType]) return NODE_VISUALS[config.actionType];
  }
  return NODE_VISUALS[nodeType] || NODE_VISUALS.action;
}

// ---------------------------------------------------------------------------
// Status ring
// ---------------------------------------------------------------------------
const STATUS_RING: Record<string, string> = {
  idle: "",
  running: "ring-2 ring-blue-400 ring-offset-2",
  completed: "ring-2 ring-green-400 ring-offset-2",
  failed: "ring-2 ring-red-400 ring-offset-2",
};

// ---------------------------------------------------------------------------
// Metadata pills
// ---------------------------------------------------------------------------
interface MetadataPill {
  label: string;
  value: string;
}

function getMetadataPills(
  nodeType: WorkflowNodeType,
  config: WorkflowNodeData["config"],
): MetadataPill[] {
  const pills: MetadataPill[] = [];

  switch (nodeType) {
    case "trigger": {
      // `config` is optional on freshly-created trigger nodes — guard the
      // `.name` read so an undefined config doesn't crash the workflow canvas.
      const name = (config as Record<string, unknown> | undefined)?.name as string | undefined;
      pills.push({ label: "Form", value: name || "Start Form" });
      break;
    }
    case "action":
      if (config.actionType === "db_query") {
        if (config.model) pills.push({ label: "Update", value: config.model });
      } else if (
        config.actionType === "db_insert" ||
        config.actionType === "db_update" ||
        config.actionType === "db_delete"
      ) {
        if (config.table) pills.push({ label: "Table", value: config.table });
      } else if (config.actionType === "set_variable") {
        if (config.variableName) pills.push({ label: "Var", value: config.variableName });
      } else if (config.actionType === "send_email") {
        if (config.to) pills.push({ label: "To", value: config.to });
        if (config.subject) pills.push({ label: "Subj", value: config.subject });
      } else if (config.actionType === "send_notification") {
        pills.push({ label: "Type", value: config.actionType });
      } else if (config.actionType === "http_call") {
        if (config.method) pills.push({ label: "Method", value: config.method });
        if (config.url) pills.push({ label: "URL", value: config.url });
      }
      break;
    case "exclusive_gateway":
    case "parallel_gateway":
      if (config.expression) pills.push({ label: "When", value: config.expression });
      break;
    case "assignment":
    case "approval":
    case "task_pool":
    case "user_task":
      if (config.pageName) pills.push({ label: "Form", value: config.pageName });
      if (config.assignType) pills.push({ label: "Assign", value: config.assignType });
      break;
    case "ai_classify":
      if (config.aiLabels?.length) pills.push({ label: "Labels", value: `${config.aiLabels.length}` });
      break;
    case "ai_extract":
      if (config.aiExtractFields?.length) pills.push({ label: "Fields", value: `${config.aiExtractFields.length}` });
      break;
    case "ai_generate":
      if (config.aiTone) pills.push({ label: "Tone", value: config.aiTone });
      break;
    case "wait":
      if (config.duration) pills.push({ label: "Delay", value: config.duration });
      break;
    case "escalation":
      if (config.slaHours) pills.push({ label: "SLA", value: `${config.slaHours}h` });
      break;
  }

  return pills;
}

// ---------------------------------------------------------------------------
// Subtitle
// ---------------------------------------------------------------------------
function getSubtitle(
  nodeType: WorkflowNodeType,
  config: WorkflowNodeData["config"] | undefined,
): string {
  if (!config) return "";
  switch (nodeType) {
    case "trigger":
      return config.description || config.type || "";
    case "action":
      if (config.actionType === "set_variable")
        return config.variableName ? `= ${config.variableName}` : "Set Variable";
      if (
        config.actionType === "db_insert" ||
        config.actionType === "db_update" ||
        config.actionType === "db_delete"
      )
        return config.table || config.actionType;
      return config.actionType || config.description || "";
    case "condition":
      return config.expression || "Expression";
    case "exclusive_gateway":
    case "parallel_gateway":
      return config.expression || "Gateway";
    case "fork":
      return "Fork";
    case "join":
      return "Join";
    case "user_task":
      return config.assignType || config.pageName || "User Task";
    case "end_event":
      return "End";
    case "decision": {
      const dt = config.decisionTable;
      if (dt) return `${dt.hitPolicy} · ${dt.rules.length} rules`;
      return "Decision table";
    }
    case "wait":
      return config.duration || "Delay";
    case "assignment":
    case "approval":
      return config.assignType || "";
    case "task_pool":
      return config.assignType || "Pool";
    case "escalation":
      return config.slaHours ? `${config.slaHours}h SLA` : "Escalation";
    case "ai_classify":
      return config.aiLabels?.length ? `${config.aiLabels.length} labels` : "Classify";
    case "ai_extract":
      return config.aiExtractFields?.length
        ? `${config.aiExtractFields.length} fields`
        : "Extract";
    case "ai_decide":
      return config.aiOptions?.length
        ? `${config.aiOptions.length} options`
        : "Decision";
    case "ai_generate":
      return config.aiTone || "Generate";
    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
// Simulator status → ring class mapping (reuses existing STATUS_RING entries)
const SIM_STATUS_RING: Record<string, string> = {
  active: STATUS_RING.running,   // blue ring
  done: STATUS_RING.completed,   // green ring
  failed: STATUS_RING.failed,    // red ring
  pending: "",                   // no ring
};

function WorkflowNodeComponent({
  data,
  selected,
}: NodeProps & { data: WorkflowNodeData & { simStatus?: "pending" | "active" | "done" | "failed" } }) {
  const { label, nodeType, config, status, simStatus } = data;
  const visual = getVisual(nodeType, config);
  const Icon = visual.icon;

  // When a simStatus is present, use the simulator ring; otherwise fall back to
  // the existing status-ring logic so the editor path is completely unchanged.
  const statusClass = simStatus !== undefined
    ? SIM_STATUS_RING[simStatus] ?? ""
    : STATUS_RING[status || "idle"] || "";

  // Opacity: pending = 0.4, done = 0.6, otherwise full
  const opacityStyle: CSSProperties =
    simStatus === "pending" ? { opacity: 0.4 }
    : simStatus === "done"  ? { opacity: 0.6 }
    : {};

  const subtitle = getSubtitle(nodeType, config);
  const pills = getMetadataPills(nodeType, config);
  const branching = isBranchingNode(nodeType);

  return (
    <div
      className={`relative min-w-[260px] max-w-[300px] rounded-xl border border-gray-200 bg-white shadow-md ${statusClass} ${
        selected ? "ring-2 ring-indigo-500 ring-offset-2" : ""
      }`}
      style={opacityStyle}
    >
      {/* Main content */}
      <div className="flex items-start gap-3 p-3">
        {/* Icon block — gradient */}
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${visual.gradient}`}
        >
          <Icon className="h-5 w-5 text-white" />
        </div>

        {/* Text */}
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex items-center gap-2">
            <span className={`truncate text-sm font-bold text-slate-800${simStatus === "done" ? " line-through" : ""}`}>
              {label}
            </span>
            {branching && (
              <span className="shrink-0 rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">
                2 out
              </span>
            )}
          </div>
          {subtitle && (
            <div className="truncate text-xs text-gray-500">{subtitle}</div>
          )}
        </div>
      </div>

      {/* Metadata pills */}
      {pills.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-gray-100 px-3 py-2">
          {pills.map((pill) => (
            <span
              key={pill.label}
              className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600"
            >
              <span className="font-medium text-gray-500">{pill.label}:</span>
              <span className="max-w-[100px] truncate">{pill.value}</span>
            </span>
          ))}
        </div>
      )}

      {/* Handles */}
      {nodeType !== "trigger" && (
        <Handle
          type="target"
          position={Position.Top}
          className="!h-2.5 !w-2.5 !bg-blue-400 !border-white !border-2"
        />
      )}
      {nodeType !== "end" && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!h-2.5 !w-2.5 !bg-blue-400 !border-white !border-2"
        />
      )}
      {/* Branching nodes: else handle on the right */}
      {branching && (
        <Handle
          type="source"
          position={Position.Right}
          id="else"
          className="!h-2.5 !w-2.5 !bg-red-400 !border-white !border-2"
        />
      )}
    </div>
  );
}

export const WorkflowNode = memo(WorkflowNodeComponent);
