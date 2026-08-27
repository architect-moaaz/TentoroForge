"use client";

import { Plus, Table2, List, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AppModel } from "@/types/app-model";

interface DataModelSidebarProps {
  appModel: AppModel;
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  onAddModel: () => void;
  width: number;
  ruleCountByTable?: Record<string, number>;
}

export function DataModelSidebar({
  appModel,
  selectedTable,
  onSelectTable,
  onAddModel,
  width,
  ruleCountByTable = {},
}: DataModelSidebarProps) {
  const tables = appModel.database?.tables ?? [];
  const enums = appModel.database?.enums ?? [];

  return (
    <div
      className="flex shrink-0 flex-col border-r bg-muted/20"
      style={{ width }}
    >
      {/* Tables section */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold uppercase text-muted-foreground">
          Tables
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5"
          onClick={onAddModel}
          title="Add model"
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tables.map((table) => (
          <button
            key={table.name}
            className={cn(
              "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted/50",
              selectedTable === table.name && "bg-muted font-medium",
            )}
            onClick={() => onSelectTable(table.name)}
          >
            <Table2 className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="truncate">{table.name}</span>
            {(ruleCountByTable[table.name] ?? 0) > 0 && (
              <span
                className="flex items-center gap-0.5 rounded-full bg-indigo-100 px-1 text-[10px] text-indigo-700"
                title={`${ruleCountByTable[table.name]} rule(s)`}
              >
                <Shield className="h-2.5 w-2.5" />
                {ruleCountByTable[table.name]}
              </span>
            )}
            <span className="ml-auto text-[10px] text-muted-foreground">
              {table.columns.length}
            </span>
          </button>
        ))}
        {tables.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            No tables yet
          </p>
        )}
      </div>

      {/* Enums section */}
      {enums.length > 0 && (
        <>
          <div className="border-t border-b px-3 py-2">
            <span className="text-xs font-semibold uppercase text-muted-foreground">
              Enums
            </span>
          </div>
          <div className="max-h-40 overflow-y-auto">
            {enums.map((e) => (
              <div
                key={e.name}
                className="flex items-center gap-2 px-3 py-1.5 text-xs"
              >
                <List className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="truncate">{e.name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {e.values.length}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
