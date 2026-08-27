"use client";
import { useState } from "react";
import type { TaskDTO } from "@/lib/workflow-sim/types";
import { taskFormSpec } from "@/lib/workflow-sim/task-form";

export function TaskInputPanel({ task, onSubmit }: { task: TaskDTO; onSubmit: (values: Record<string, unknown>) => void; }) {
  const spec = taskFormSpec(task);
  const [values, setValues] = useState<Record<string, string>>({});
  const set = (k: string, v: string) => setValues((s) => ({ ...s, [k]: v }));

  return (
    <div className="border-2 border-amber-400 bg-amber-50 rounded p-3 space-y-2">
      <div className="font-medium text-amber-800 text-sm">⏸ Input required · {task.node_label ?? task.node_id}</div>
      {spec.kind === "json" ? (
        <textarea className="w-full border rounded p-2 font-mono text-xs" rows={4} placeholder="{}" value={values.__json ?? ""} onChange={(e) => set("__json", e.target.value)} />
      ) : (
        spec.fields.map((f) => (
          <label key={f.name} className="block text-sm">
            <span>{f.name}{f.required ? " *" : ""}</span>
            {f.type === "select" ? (
              <select className="w-full border rounded p-1" value={values[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)}>
                <option value="">—</option>
                {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input className="w-full border rounded p-1" type={f.type === "number" ? "number" : "text"} value={values[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)} />
            )}
          </label>
        ))
      )}
      <button className="bg-amber-600 text-white rounded px-3 py-1.5 text-sm w-full" onClick={() => onSubmit(values)}>Submit &amp; continue ▸</button>
    </div>
  );
}
