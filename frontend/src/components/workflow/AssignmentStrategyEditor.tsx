"use client";

/**
 * AssignmentStrategyEditor — configures who gets assigned a workflow task.
 *
 * Strategies:
 * - role: any user with this role
 * - entity_field: user ID from an entity field
 * - reporting_manager: entity creator's manager
 * - department_head: head of the relevant department
 * - round_robin: rotate among users with role
 * - creator: the user who created the entity
 * - group: any member of a group/team
 */

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AssignmentConfig, AssignmentStrategy } from "@/types/workflow";

interface AssignmentStrategyEditorProps {
  assignment: AssignmentConfig;
  onChange: (assignment: AssignmentConfig) => void;
}

const STRATEGIES: Array<{ value: AssignmentStrategy; label: string; description: string; needsValue: boolean }> = [
  { value: "role", label: "By Role", description: "Any user with this role", needsValue: true },
  { value: "entity_field", label: "Entity Field", description: "User ID from entity field", needsValue: true },
  { value: "reporting_manager", label: "Reporting Manager", description: "Creator's direct manager", needsValue: false },
  { value: "department_head", label: "Department Head", description: "Head of the department", needsValue: false },
  { value: "round_robin", label: "Round Robin", description: "Rotate among users with role", needsValue: true },
  { value: "creator", label: "Creator", description: "The user who created the entity", needsValue: false },
  { value: "group", label: "Group/Team", description: "Any member of this group", needsValue: true },
];

export function AssignmentStrategyEditor({ assignment, onChange }: AssignmentStrategyEditorProps) {
  const strategy = STRATEGIES.find((s) => s.value === assignment.strategy) || STRATEGIES[0];

  return (
    <div className="space-y-2">
      <div>
        <Label className="text-[10px] font-semibold">Assignment Strategy</Label>
        <Select
          value={assignment.strategy}
          onValueChange={(v) => onChange({ ...assignment, strategy: v as AssignmentStrategy })}
        >
          <SelectTrigger className="mt-1 h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STRATEGIES.map((s) => (
              <SelectItem key={s.value} value={s.value} className="text-xs">
                <div>
                  <span className="font-medium">{s.label}</span>
                  <span className="ml-1.5 text-muted-foreground text-[10px]">— {s.description}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {strategy.needsValue && (
        <div>
          <Label className="text-[10px]">
            {assignment.strategy === "role" ? "Role Name" :
             assignment.strategy === "entity_field" ? "Field Name" :
             assignment.strategy === "round_robin" ? "Role Name" :
             assignment.strategy === "group" ? "Group Name" : "Value"}
          </Label>
          <Input
            className="h-7 text-xs"
            placeholder={
              assignment.strategy === "role" ? "e.g. Doctor, Manager, Admin" :
              assignment.strategy === "entity_field" ? "e.g. primaryPhysicianId, assigneeId" :
              assignment.strategy === "round_robin" ? "e.g. Reviewer" :
              assignment.strategy === "group" ? "e.g. Finance Team" : ""
            }
            value={assignment.value || ""}
            onChange={(e) => onChange({ ...assignment, value: e.target.value })}
          />
        </div>
      )}

      <div>
        <Label className="text-[10px]" htmlFor="wf-fallback-if-primary-assignee-unavailable">Fallback (if primary assignee unavailable)</Label>
        <Input
          id="wf-fallback-if-primary-assignee-unavailable"
          className="h-7 text-xs"
          placeholder="e.g. role:Admin"
          value={assignment.fallback || ""}
          onChange={(e) => onChange({ ...assignment, fallback: e.target.value })}
        />
      </div>

      <div>
        <Label className="text-[10px]" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="h-7 text-xs"
          placeholder="e.g. Assigned to the patient's primary physician"
          value={assignment.description || ""}
          onChange={(e) => onChange({ ...assignment, description: e.target.value })}
        />
      </div>
    </div>
  );
}
