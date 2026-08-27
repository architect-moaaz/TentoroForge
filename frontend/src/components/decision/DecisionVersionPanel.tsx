"use client";

import { useState } from "react";
import {
  GitBranch,
  Clock,
  ArrowLeftRight,
  Save,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDecisionStore, type DecisionVersion } from "@/stores/decision";
import { DecisionDiffView } from "./DecisionDiffView";

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function DecisionVersionPanel() {
  const activeTable = useDecisionStore((s) => s.activeTable);
  const versions = useDecisionStore((s) => s.versions);
  const saveVersion = useDecisionStore((s) => s.saveVersion);
  const clearVersions = useDecisionStore((s) => s.clearVersions);

  const [compareA, setCompareA] = useState<string>("");
  const [compareB, setCompareB] = useState<string>("");

  const handleSaveVersion = () => {
    saveVersion(`v${versions.length + 1}`);
  };

  const versionA =
    compareA !== "" ? versions[parseInt(compareA, 10)] : undefined;
  const versionB =
    compareB !== "" ? versions[parseInt(compareB, 10)] : undefined;

  // Auto-compare: if we have at least 2 versions and no selection, default to last two
  const autoCompareA =
    !versionA && versions.length >= 2
      ? versions[versions.length - 2]
      : undefined;
  const autoCompareB =
    !versionB && versions.length >= 2
      ? versions[versions.length - 1]
      : undefined;

  const diffOld = versionA || autoCompareA;
  const diffNew = versionB || autoCompareB;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Version History</span>
          <Badge variant="secondary" className="text-[10px]">
            {versions.length} version{versions.length !== 1 ? "s" : ""}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleSaveVersion}
            disabled={!activeTable}
          >
            <Save className="mr-1 h-3 w-3" />
            Save Version
          </Button>
          {versions.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-muted-foreground"
              onClick={clearVersions}
            >
              <Trash2 className="mr-1 h-3 w-3" />
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* Version list */}
      {versions.length > 0 && (
        <div className="space-y-1">
          {versions.map((v, i) => (
            <div
              key={i}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/50"
            >
              <Clock className="h-3 w-3 text-muted-foreground" />
              <span className="font-medium">{v.label}</span>
              <span className="text-muted-foreground">{formatTime(v.timestamp)}</span>
              <span className="text-muted-foreground">
                {v.table.rules.length} rule{v.table.rules.length !== 1 ? "s" : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Compare selector */}
      {versions.length >= 2 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs font-medium">Compare Versions</span>
          </div>
          <div className="flex items-center gap-2">
            <Select value={compareA} onValueChange={setCompareA}>
              <SelectTrigger className="h-7 w-[140px] text-xs">
                <SelectValue placeholder="Older version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v, i) => (
                  <SelectItem key={i} value={String(i)} className="text-xs">
                    {v.label} ({formatTime(v.timestamp)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">vs</span>
            <Select value={compareB} onValueChange={setCompareB}>
              <SelectTrigger className="h-7 w-[140px] text-xs">
                <SelectValue placeholder="Newer version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v, i) => (
                  <SelectItem key={i} value={String(i)} className="text-xs">
                    {v.label} ({formatTime(v.timestamp)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      {/* Diff display */}
      {diffOld && diffNew && diffOld !== diffNew && (
        <DecisionDiffView
          oldTable={diffOld.table}
          newTable={diffNew.table}
          oldLabel={diffOld.label}
          newLabel={diffNew.label}
        />
      )}

      {/* Empty state */}
      {versions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <GitBranch className="mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">
            No versions saved yet. Save a version to track changes
            <br />
            and compare different iterations of your decision table.
          </p>
        </div>
      )}
    </div>
  );
}
