"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Database, Table2, BookOpen } from "lucide-react";
import type { DRDNodeType } from "@/types/decision";

interface DRDNodeData extends Record<string, unknown> {
  label: string;
  drdType: DRDNodeType;
  decisionTableId?: string;
  variableName?: string;
  variableType?: string;
  url?: string;
  description?: string;
}

const DRD_STYLES: Record<
  DRDNodeType,
  { bg: string; border: string; icon: typeof Table2 }
> = {
  inputData: {
    bg: "bg-sky-50",
    border: "border-sky-400",
    icon: Database,
  },
  decision: {
    bg: "bg-indigo-50",
    border: "border-indigo-400",
    icon: Table2,
  },
  knowledgeSource: {
    bg: "bg-amber-50",
    border: "border-amber-400",
    icon: BookOpen,
  },
};

/** Oval shape for InputData nodes */
function InputDataShape({
  children,
  selected,
}: {
  children: React.ReactNode;
  selected: boolean;
}) {
  return (
    <div
      className={`min-w-[140px] max-w-[200px] border-2 border-sky-400 bg-sky-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
      style={{ borderRadius: "50%" }}
    >
      <div className="px-5 py-3">{children}</div>
    </div>
  );
}

/** Rectangle shape for Decision nodes */
function DecisionShape({
  children,
  selected,
}: {
  children: React.ReactNode;
  selected: boolean;
}) {
  return (
    <div
      className={`min-w-[140px] max-w-[200px] rounded-lg border-2 border-indigo-400 bg-indigo-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="px-3 py-2">{children}</div>
    </div>
  );
}

/** Wavy/document shape for KnowledgeSource nodes */
function KnowledgeSourceShape({
  children,
  selected,
}: {
  children: React.ReactNode;
  selected: boolean;
}) {
  return (
    <div
      className={`relative min-w-[140px] max-w-[200px] ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1 rounded-lg" : ""
      }`}
    >
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 200 70"
        preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M0,0 L200,0 L200,55 Q175,65 150,55 Q125,45 100,55 Q75,65 50,55 Q25,45 0,55 Z"
          fill="#fffbeb"
          stroke="#f59e0b"
          strokeWidth="2"
        />
      </svg>
      <div className="relative px-3 py-2 pb-4">{children}</div>
    </div>
  );
}

function DRDNodeComponent({
  data,
  selected,
}: NodeProps & { data: DRDNodeData }) {
  const { label, drdType } = data;
  const style = DRD_STYLES[drdType] || DRD_STYLES.decision;
  const Icon = style.icon;

  const content = (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 shrink-0 text-slate-600" />
      <div className="min-w-0 flex-1">
        <span className="text-xs font-semibold text-slate-800 truncate block">
          {label}
        </span>
        {drdType === "inputData" && data.variableName && (
          <span className="text-[10px] text-slate-500 truncate block">
            {data.variableName}: {data.variableType || "any"}
          </span>
        )}
        {drdType === "decision" && data.decisionTableId && (
          <span className="text-[10px] text-slate-500 truncate block">
            table linked
          </span>
        )}
        {drdType === "knowledgeSource" && data.url && (
          <span className="text-[10px] text-slate-500 truncate block">
            {data.url}
          </span>
        )}
      </div>
    </div>
  );

  let shape: React.ReactNode;
  if (drdType === "inputData") {
    shape = <InputDataShape selected={!!selected}>{content}</InputDataShape>;
  } else if (drdType === "knowledgeSource") {
    shape = (
      <KnowledgeSourceShape selected={!!selected}>
        {content}
      </KnowledgeSourceShape>
    );
  } else {
    shape = <DecisionShape selected={!!selected}>{content}</DecisionShape>;
  }

  return (
    <>
      {shape}
      {/* Target handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2 !h-2 !bg-slate-400 !border-white !border-2"
      />
      {/* Source handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2 !h-2 !bg-slate-400 !border-white !border-2"
      />
    </>
  );
}

export const DRDNode = memo(DRDNodeComponent);
