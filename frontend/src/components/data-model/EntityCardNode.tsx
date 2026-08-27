"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  KeyRound,
  CircleDot,
  MoreHorizontal,
  Plus,
  Link,
  Shield,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ColumnModel, RelationModel } from "@/types/app-model";

export interface EntityCardData extends Record<string, unknown> {
  label: string;
  columns: ColumnModel[];
  relations?: RelationModel[];
  ruleCount?: number;
  onAddField?: (tableName: string) => void;
  onEditField?: (tableName: string, columnName: string) => void;
  onDeleteModel?: (tableName: string) => void;
  onAddIndex?: (tableName: string) => void;
  onAddRelation?: (tableName: string) => void;
  onSelectTable?: (tableName: string) => void;
}

const TYPE_COLORS: Record<string, string> = {
  serial: "bg-purple-100 text-purple-700",
  integer: "bg-blue-100 text-blue-700",
  bigint: "bg-blue-100 text-blue-700",
  smallint: "bg-blue-100 text-blue-700",
  boolean: "bg-amber-100 text-amber-700",
  text: "bg-green-100 text-green-700",
  varchar: "bg-green-100 text-green-700",
  char: "bg-green-100 text-green-700",
  uuid: "bg-indigo-100 text-indigo-700",
  timestamp: "bg-rose-100 text-rose-700",
  date: "bg-rose-100 text-rose-700",
  time: "bg-rose-100 text-rose-700",
  json: "bg-orange-100 text-orange-700",
  jsonb: "bg-orange-100 text-orange-700",
  real: "bg-teal-100 text-teal-700",
  doublePrecision: "bg-teal-100 text-teal-700",
  numeric: "bg-teal-100 text-teal-700",
  decimal: "bg-teal-100 text-teal-700",
};

function getTypeColor(type: string): string {
  return TYPE_COLORS[type] || "bg-gray-100 text-gray-700";
}

function EntityCardNodeComponent({ data }: NodeProps & { data: EntityCardData }) {
  const { label, columns, relations, ruleCount, onAddField, onEditField, onDeleteModel, onAddIndex, onAddRelation, onSelectTable } = data;

  return (
    <div className="min-w-[240px] rounded-lg border bg-white shadow-md">
      {/* Header */}
      <div className="flex items-center justify-between rounded-t-lg border-b bg-slate-50 px-3 py-2">
        <span
          className={onSelectTable ? "text-sm font-semibold text-slate-800 cursor-pointer hover:underline" : "text-sm font-semibold text-slate-800"}
          onClick={onSelectTable ? () => onSelectTable(label) : undefined}
          title={onSelectTable ? "View data" : undefined}
        >
          {label}
        </span>
        <div className="flex items-center gap-1">
          {ruleCount != null && ruleCount > 0 && (
            <span
              className="flex items-center gap-0.5 rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700"
              title={`${ruleCount} rule(s)`}
            >
              <Shield className="h-2.5 w-2.5" />
              {ruleCount}
            </span>
          )}
          {onAddField && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={(e) => {
                e.stopPropagation();
                onAddField(label);
              }}
              title="Add field"
            >
              <Plus className="h-3 w-3" />
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-6 w-6">
                <MoreHorizontal className="h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onAddField && (
                <DropdownMenuItem onClick={() => onAddField(label)}>
                  Add Field
                </DropdownMenuItem>
              )}
              {onAddRelation && (
                <DropdownMenuItem onClick={() => onAddRelation(label)}>
                  Add Relationship
                </DropdownMenuItem>
              )}
              {onAddIndex && (
                <DropdownMenuItem onClick={() => onAddIndex(label)}>
                  Add Index
                </DropdownMenuItem>
              )}
              {onDeleteModel && (
                <DropdownMenuItem
                  className="text-red-600"
                  onClick={() => onDeleteModel(label)}
                >
                  Delete Model
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Columns */}
      <div className="divide-y">
        {columns.map((col) => (
          <div
            key={col.name}
            className="group flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-slate-50"
            onClick={() => onEditField?.(label, col.name)}
          >
            <div className="flex items-center gap-1 min-w-0 flex-1">
              {col.primaryKey && (
                <KeyRound className="h-3 w-3 shrink-0 text-amber-500" />
              )}
              {col.references && (
                <Link className="h-3 w-3 shrink-0 text-blue-500" />
              )}
              <span className="truncate font-medium text-slate-700">
                {col.name}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Badge
                variant="secondary"
                className={`text-[10px] px-1.5 py-0 font-mono ${getTypeColor(col.type)}`}
              >
                {col.type}
              </Badge>
              {col.nullable && (
                <span title="Nullable">
                  <CircleDot className="h-3 w-3 text-gray-400" />
                </span>
              )}
              {col.unique && (
                <span className="text-[10px] text-violet-500 font-medium" title="Unique">U</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Handles for edges */}
      <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-blue-400" />
      <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-blue-400" />
    </div>
  );
}

export const EntityCardNode = memo(EntityCardNodeComponent);
