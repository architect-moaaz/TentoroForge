"use client";

import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { FieldAccessMatrix } from "./FieldAccessMatrix";
import { RecordScopeEditor } from "./RecordScopeEditor";

interface AccessSubPanelProps {
  projectId: string;
  orgId: string;
}

export function AccessSubPanel({ projectId, orgId }: AccessSubPanelProps) {
  return (
    <div className="flex-1 overflow-auto p-4 space-y-6">
      <div>
        <h3 className="text-sm font-semibold">Field Access Matrix</h3>
        <p className="text-xs text-muted-foreground mb-3">
          Control which fields each role can view or edit. Click a cell to cycle through: Edit → View → Hidden.
        </p>
        <FieldAccessMatrix projectId={projectId} orgId={orgId} />
      </div>

      <Separator />

      <div>
        <h3 className="text-sm font-semibold">Record Scope</h3>
        <p className="text-xs text-muted-foreground mb-3">
          Define which records each role can read, as a condition over the
          record&apos;s own fields and the acting user. The generated app
          compiles it into the query&apos;s WHERE clause, so a row a role
          cannot read is also absent from its counts and totals.
        </p>
        <RecordScopeEditor projectId={projectId} orgId={orgId} />
      </div>
    </div>
  );
}
