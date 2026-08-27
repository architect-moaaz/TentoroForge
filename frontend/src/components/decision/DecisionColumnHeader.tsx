"use client";

import { useState } from "react";
import { X, MoreVertical, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { DecisionTableInput, DecisionTableOutput } from "@/types/decision";

interface DecisionColumnHeaderProps {
  column: DecisionTableInput | DecisionTableOutput;
  columnType: "input" | "output";
  onRename: (name: string) => void;
  onChangeType: (type: DecisionTableInput["type"]) => void;
  onDelete: () => void;
  readOnly?: boolean;
}

export function DecisionColumnHeader({
  column,
  columnType,
  onRename,
  onChangeType,
  onDelete,
  readOnly,
}: DecisionColumnHeaderProps) {
  const [renaming, setRenaming] = useState(false);
  const [nameValue, setNameValue] = useState(column.name);

  const commitRename = () => {
    setRenaming(false);
    if (nameValue.trim() && nameValue !== column.name) {
      onRename(nameValue.trim());
    } else {
      setNameValue(column.name);
    }
  };

  return (
    <th
      className={`border px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider ${
        columnType === "input"
          ? "bg-blue-50 text-blue-700"
          : "bg-emerald-50 text-emerald-700"
      }`}
    >
      <div className="flex items-center gap-1">
        {renaming ? (
          <Input
            className="h-5 text-[10px] px-1 w-full"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameValue(column.name);
                setRenaming(false);
              }
            }}
            autoFocus
          />
        ) : (
          <>
            <span className="flex-1 truncate">{column.label || column.name}</span>
            <span className="shrink-0 rounded bg-white/50 px-1 text-[9px] font-normal">
              {column.type}
            </span>
            {!readOnly && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-4 w-4 shrink-0">
                    <MoreVertical className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="text-xs">
                  <DropdownMenuItem onClick={() => setRenaming(true)}>
                    <Pencil className="h-3 w-3 mr-2" />
                    Rename
                  </DropdownMenuItem>
                  {(["string", "number", "boolean", "date", "any"] as const).map((t) => (
                    <DropdownMenuItem
                      key={t}
                      onClick={() => onChangeType(t)}
                      className={column.type === t ? "font-semibold" : ""}
                    >
                      Type: {t}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuItem
                    onClick={onDelete}
                    className="text-red-600 focus:text-red-600"
                  >
                    <X className="h-3 w-3 mr-2" />
                    Delete Column
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </>
        )}
      </div>
    </th>
  );
}
