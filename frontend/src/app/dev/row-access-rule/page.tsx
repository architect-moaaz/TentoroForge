"use client";

/**
 * Dev-only page: RowAccessRuleForm on its own, with the model and field names
 * supplied locally.
 *
 * The real form lives inside RuleFormDialog on
 * /org/[orgId]/projects/[projectId], which needs a session, an org and a
 * project before it will render a single pixel — too much standing between a
 * change to this form and seeing whether it works. Same reasoning, and the
 * same /dev/* convention, as the other preview pages here.
 *
 * The org-roles query still runs and will simply come back empty without a
 * backend, which exercises the "no roles" branch. Point it at a real orgId
 * with the API up to see the grant chips.
 */
import { useState } from "react";
import { RowAccessRuleForm } from "@/components/rules/RowAccessRuleForm";
import type { RuleConfig } from "@/types/rules";

const MODELS = ["Application", "Candidate", "Interview"];
const FIELDS = [
  "id",
  "currentStage",
  "status",
  "createdByUserId",
  "stageEnteredAt",
  "source",
];

export default function RowAccessRulePreview() {
  const [config, setConfig] = useState<RuleConfig>({});
  const [modelName, setModelName] = useState(MODELS[0]);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8 text-sm">
      <div>
        <h1 className="text-lg font-semibold">RowAccessRuleForm preview</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          Build a condition; the compiled FEEL-lite appears below it. That
          string is what the data engine turns into the query&apos;s WHERE
          clause.
        </p>
      </div>

      <div className="rounded-lg border p-4">
        <RowAccessRuleForm
          orgId="dev-preview"
          modelNames={MODELS}
          fieldNames={FIELDS}
          config={config}
          modelName={modelName}
          onConfigChange={setConfig}
          onModelChange={setModelName}
        />
      </div>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          Rule as it would be saved
        </h2>
        <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 text-[11px]">
          {JSON.stringify(
            { rule_type: "row_access", model_name: modelName, config },
            null,
            2,
          )}
        </pre>
      </section>
    </div>
  );
}
