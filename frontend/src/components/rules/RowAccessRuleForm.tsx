"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConditionBuilder } from "./ConditionBuilder";
import { conditionToFeel } from "@/lib/condition-to-feel";
import type { ConditionExpression, RuleConfig } from "@/types/rules";

/**
 * Authoring for a `row_access` rule — which ROWS a role may reach.
 *
 * The sibling Access Control form is a role x action grid: it decides whether
 * a role may read a model at all, and which columns come back. This decides
 * *which rows* come back, by a condition over the row's own values and the
 * acting user.
 *
 * The condition is built with the same visual tree the business-rules editor
 * uses and compiled to FEEL-lite by the same `conditionToFeel`, because the
 * data engine compiles that FEEL into the query's WHERE clause. Two things
 * follow from it being a WHERE clause rather than a filter applied afterwards:
 * a row the rule excludes is also absent from counts, pages and aggregates —
 * and a condition the engine cannot turn into SQL is refused at read time
 * rather than silently ignored, which is why the note below says so.
 */
interface RowAccessRuleFormProps {
  orgId: string;
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
}

interface OrgRole {
  id: string;
  name: string;
}

export function RowAccessRuleForm({
  orgId,
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: RowAccessRuleFormProps) {
  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  const granted = config.roles ?? [];

  const toggleRole = (name: string) => {
    const next = granted.includes(name)
      ? granted.filter((r) => r !== name)
      : [...granted, name];
    onConfigChange({ ...config, roles: next });
  };

  // The tree is what the author edits; the FEEL is what the engine compiles.
  // Both are stored so the rule round-trips back into this editor.
  const setCondition = (when: ConditionExpression | null) => {
    onConfigChange({ ...config, when, whenFeel: conditionToFeel(when) });
  };

  // A rule saved without the builder ever being touched still has to carry a
  // condition. The engine reads `whenFeel`, and an absent one is not a
  // condition it can compile — so it refuses the read and the role sees
  // nothing, which is the exact opposite of the "grants every row" rule the
  // copy above tells you to write for a role that should see everything.
  // The empty condition is therefore written down as `true` when the form
  // opens, rather than left implied by a missing key.
  useEffect(() => {
    if (config.whenFeel === undefined) {
      const when = config.when ?? null;
      onConfigChange({ ...config, when, whenFeel: conditionToFeel(when) });
    }
  }, [config, onConfigChange]);

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Model</Label>
        <Select value={modelName} onValueChange={onModelChange}>
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue placeholder="Select model..." />
          </SelectTrigger>
          <SelectContent>
            {modelNames.map((m) => (
              <SelectItem key={m} value={m} className="text-xs">
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">Grants to</Label>
        <p className="mt-1 text-xs text-muted-foreground">
          Rules on a model add up: a role reaches a row if any rule granted to
          it admits that row. A role no rule names reaches no rows at all, so
          give every role that should see everything a rule with an empty
          condition.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {roles.map((role) => (
            <Badge
              key={role.id}
              variant={granted.includes(role.name) ? "default" : "outline"}
              className="cursor-pointer text-xs"
              onClick={() => toggleRole(role.name)}
            >
              {role.name}
            </Badge>
          ))}
          {roles.length === 0 && (
            <span className="text-xs text-muted-foreground">
              No org roles found. Create roles in org settings first.
            </span>
          )}
        </div>
        {granted.length === 0 && roles.length > 0 && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            No role selected — this rule grants to every role.
          </p>
        )}
      </div>

      <div>
        <Label className="text-xs">Readable when</Label>
        <p className="mt-1 mb-2 text-xs text-muted-foreground">
          Compare the record&apos;s own fields against a value or against{" "}
          <code className="text-[11px]">user.id</code>. An empty condition means
          every row.
        </p>
        <ConditionBuilder
          value={config.when ?? null}
          onChange={setCondition}
          fields={fieldNames}
        />
      </div>

      {config.whenFeel && (
        <div className="rounded-md border bg-muted/40 p-2">
          <Label className="text-xs text-muted-foreground">
            Compiled to the query&apos;s WHERE clause
          </Label>
          <pre className="mt-1 overflow-x-auto text-[11px]">{config.whenFeel}</pre>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Comparisons, <code>in</code>, ranges and and/or/not become SQL.
            Anything else — a function call, arithmetic — cannot, and the rule
            returns no rows rather than being skipped.
          </p>
        </div>
      )}
    </div>
  );
}
