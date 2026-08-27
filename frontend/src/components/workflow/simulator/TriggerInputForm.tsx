"use client";
import { useState } from "react";
import type { WorkflowDefinition } from "@/types/workflow";
import { extractTriggerFields, coerceTriggerValues } from "@/lib/workflow-sim/trigger-form";

export function TriggerInputForm({ def, onRun }: { def: WorkflowDefinition; onRun: (variables: Record<string, unknown>) => void; }) {
  const fields = extractTriggerFields(def);
  const [values, setValues] = useState<Record<string, string>>({});
  const [json, setJson] = useState("{}");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (fields.length === 0) {
      try {
        onRun(JSON.parse(json || "{}"));
        setError(null);
      } catch {
        setError("Invalid JSON — please fix and try again.");
      }
      return;
    }
    onRun(coerceTriggerValues(fields, values));
  };

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium">Trigger inputs</h4>
      {fields.length === 0 ? (
        <textarea className="w-full border rounded p-2 font-mono text-xs" rows={5} value={json} onChange={(e) => setJson(e.target.value)} />
      ) : (
        fields.map((f) => (
          <label key={f.name} className="block text-sm">
            <span>{f.name}{f.required ? " *" : ""}</span>
            {f.type === "boolean" ? (
              <input type="checkbox" checked={values[f.name] === "true"} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.checked ? "true" : "" }))} />
            ) : (
              <input className="w-full border rounded p-1" type={f.type === "number" ? "number" : "text"} value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
            )}
          </label>
        ))
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
      <button className="bg-blue-600 text-white rounded px-3 py-1.5 text-sm" onClick={submit}>▶ Run</button>
    </div>
  );
}
