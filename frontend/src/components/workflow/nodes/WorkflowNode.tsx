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
  ClipboardCheck,
} from "lucide-react";
import { visualFor } from "@/catalog/workflowNodes";
import type { WorkflowNodeData, WorkflowNodeType } from "@/types/workflow";

// ---------------------------------------------------------------------------
// Icon lookup
// ---------------------------------------------------------------------------
const ICONS: Record<string, typeof Zap> = {
  Zap, Play, GitBranch, Clock, Square, UserPlus, CheckCircle, Users,
  ArrowUpCircle, Brain, ScanText, Sparkles, Table2, Hand, Webhook,
  Calendar, Database, Globe, Mail, Bell, Split, GitMerge, Hash, FileText, Plug,
  ClipboardCheck,
};

// ---------------------------------------------------------------------------
// Visuals — icon + gradient come from the workflow node catalog, so the node
// on the canvas, the palette entry it was dragged from and the node the agent
// authored are one definition.
// ---------------------------------------------------------------------------
interface NodeVisual {
  gradient: string;
  icon: typeof Zap;
}

function getVisual(nodeType: WorkflowNodeType, config: WorkflowNodeData["config"] | undefined): NodeVisual {
  const { icon, gradient } = visualFor(nodeType, config as Record<string, unknown> | undefined);
  return { gradient, icon: ICONS[icon] || Play };
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

/**
 * A subtitle/pill value must be a plain string — config is LLM-generated and a
 * field the card reads (expression, duration, table, …) can arrive as an object
 * or array. Rendering that as a React child throws "Objects are not valid as a
 * React child" and, with no error boundary in the tree, blank-screens the whole
 * editor. Coerce: strings pass through, other primitives stringify, objects fall
 * back to `fb`.
 */
function asText(v: unknown, fb = ""): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return fb;
}

/**
 * Read an action input by name. The v2 contract editor writes values into
 * `config.inputMappings` (as `{name, source:"literal", value}`), NOT the flat
 * legacy keys the card historically read — so a table/recipient set in the panel
 * showed no pill. Prefer the literal mapping, fall back to the flat key.
 */
function readInput(config: WorkflowNodeData["config"] | undefined, name: string): string {
  const mappings = (config as Record<string, unknown> | undefined)?.inputMappings;
  if (Array.isArray(mappings)) {
    const m = mappings.find(
      (x) => x && typeof x === "object" && (x as { name?: string }).name === name,
    ) as { source?: string; value?: unknown } | undefined;
    if (m && m.source === "literal") return asText(m.value);
  }
  return asText((config as Record<string, unknown> | undefined)?.[name]);
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
    case "action": {
      const table = readInput(config, "table");
      if (config.actionType === "db_query") {
        if (table) pills.push({ label: "Query", value: table });
      } else if (
        config.actionType === "db_insert" ||
        config.actionType === "db_update" ||
        config.actionType === "db_delete"
      ) {
        if (table) pills.push({ label: "Table", value: table });
      } else if (config.actionType === "set_variable") {
        const v = readInput(config, "variableName") || asText(config.variableName);
        if (v) pills.push({ label: "Var", value: v });
      } else if (config.actionType === "send_email") {
        const to = readInput(config, "to"), subject = readInput(config, "subject");
        if (to) pills.push({ label: "To", value: to });
        if (subject) pills.push({ label: "Subj", value: subject });
      } else if (config.actionType === "send_notification") {
        pills.push({ label: "Type", value: asText(config.actionType) });
      } else if (config.actionType === "http_call") {
        const method = readInput(config, "method"), url = readInput(config, "url");
        if (method) pills.push({ label: "Method", value: method });
        if (url) pills.push({ label: "URL", value: url });
      }
      break;
    }
    case "exclusive_gateway":
    case "parallel_gateway":
      if (config.expression) pills.push({ label: "When", value: asText(config.expression, "condition") });
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
      if (config.duration) pills.push({ label: "Delay", value: asText(config.duration, "delay") });
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
    case "action": {
      if (config.actionType === "set_variable") {
        const v = readInput(config, "variableName") || asText(config.variableName);
        return v ? `= ${v}` : "Set Variable";
      }
      if (
        config.actionType === "db_insert" ||
        config.actionType === "db_update" ||
        config.actionType === "db_delete"
      )
        return readInput(config, "table") || asText(config.actionType);
      return asText(config.actionType) || asText(config.description);
    }
    case "condition":
      return asText(config.expression, "Expression");
    case "exclusive_gateway":
    case "parallel_gateway":
      return asText(config.expression, "Gateway");
    case "fork":
      return "Fork";
    case "join":
      return "Join";
    case "user_task":
      return config.assignType || config.pageName || "User Task";
    case "end_event":
      return "End";
    case "decision": {
      // config.decisionTable is LLM-generated and may be a truthy-but-malformed
      // shape ({}, [], a string, or missing rules). Only read .rules when it is
      // actually an array — otherwise .length throws and blank-screens the editor.
      const dt = config.decisionTable as { hitPolicy?: unknown; rules?: unknown } | undefined;
      if (dt && Array.isArray(dt.rules)) return `${asText(dt.hitPolicy, "F")} · ${dt.rules.length} rules`;
      return "Decision table";
    }
    case "wait":
      return asText(config.duration, "Delay");
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
