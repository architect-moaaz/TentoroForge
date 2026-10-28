"use client";
/**
 * The questions a guided part asks before it is added: which workflow a form saves or a button runs, which kind of record a list shows.
 * The same three as the website's palette. Only names are chosen here and a few words typed; the server writes the code from the
 * Blueprint, and the phone's compiler has the last word.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { holderIdOf, rowVarAt, type Place } from "./phoneParts";
import type { GuideKind, GuideRefs, GuideSpec, PhonePart } from "./types";

const TITLES: Record<GuideKind, string> = {
  form: "What should this form save?",
  button: "What should the button do?",
  list: "What should the list show?",
};

function humanise(name: string): string {
  return name.replace(/([A-Z])/g, " $1").replace(/[_-]+/g, " ").trim().replace(/^./, (c) => c.toUpperCase());
}

/** The question a person answers for one input of a workflow a button sends: a fixed word or number. */
function hint(type: string): string {
  return /number|int|decimal|float|money/i.test(type) ? "A number" : /bool/i.test(type) ? "yes or no" : "A word or two";
}

export function GuidedDialog({ guide, refs, nodes, busy, onClose, onAdd }: {
  guide: { kind: GuideKind; place: Place };
  refs: GuideRefs;
  nodes: Record<string, PhonePart>;
  busy: boolean;
  onClose: () => void;
  onAdd: (spec: GuideSpec) => Promise<boolean>;
}) {
  const { kind, place } = guide;
  const [workflowId, setWorkflowId] = useState(refs.workflows[0]?.id ?? "");
  const [label, setLabel] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [entityName, setEntityName] = useState(refs.entities[0]?.name ?? "");
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");

  const workflow = refs.workflows.find((w) => w.id === workflowId) ?? null;
  const entity = refs.entities.find((e) => e.name === entityName) ?? null;
  const fields = (entity?.fields ?? []).filter((f) => f.name !== "id");
  useEffect(() => {
    const first = fields.find((f) => /^(name|title|label)$/i.test(f.name)) ?? fields[0];
    setTitle(first?.name ?? "");
    setSubtitle("");
  }, [entityName]); // eslint-disable-line react-hooks/exhaustive-deps

  const row = rowVarAt(nodes, holderIdOf(nodes, place));
  const sent = (workflow?.inputs ?? []).filter((i) => i.required);
  const needsRecord = kind === "button" && sent.some((i) => i.kind === "record") && !row;
  const missing = kind === "button" ? sent.filter((i) => i.kind !== "record" && !(values[i.name] ?? "").trim()) : [];

  const problem = (() => {
    if (kind === "list") return !entity ? "This application has no kinds of record yet." : !title ? "Choose what each row should say." : "";
    if (!workflow) return "This application has no workflows yet. Ask Smith to add one, for example “let people submit a request”.";
    if (needsRecord) {
      const record = sent.find((i) => i.kind === "record");
      return `“${workflow.name}” acts on one ${record?.entity ?? "record"}, so the button has to sit in a row of a list of them. Close this and drop it inside a box or a row that is part of a list item.`;
    }
    return "";
  })();

  const summary = (() => {
    if (kind === "form" && workflow) return `A form with ${workflow.inputs.length} field${workflow.inputs.length === 1 ? "" : "s"} that runs “${workflow.name}”.`;
    if (kind === "button" && workflow) return `A “${label.trim() || workflow.name}” button that runs “${workflow.name}”${sent.some((i) => i.kind === "record") && row ? " on the row's record" : ""}.`;
    if (kind === "list" && entity && title) return `A list of ${entity.name} records, each row saying its ${humanise(title).toLowerCase()}${subtitle ? ` and ${humanise(subtitle).toLowerCase()}` : ""}.`;
    return "";
  })();

  const spec = (): GuideSpec => {
    const at = place.op;
    if (kind === "form") return { kind, place: at, workflow: workflowId };
    if (kind === "button") return { kind, place: at, workflow: workflowId, label: label.trim() || undefined, values };
    return { kind, place: at, entity: entityName, title, subtitle: subtitle || undefined };
  };
  const ready = !problem && missing.length === 0 && !busy;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-lg" data-testid="guided-dialog">
        <DialogHeader>
          <DialogTitle>{TITLES[kind]}</DialogTitle>
          <DialogDescription>It is added {place.says}.</DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] space-y-3 overflow-auto">
          {kind !== "list" && (refs.workflows.length ? (
            <div className="space-y-1" role="radiogroup" aria-label="Workflow">
              {refs.workflows.map((w) => (
                <label key={w.id} className={cn("flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm", workflowId === w.id ? "border-primary bg-primary/5" : "border-border")}>
                  <input type="radio" name="workflow" className="mt-1" checked={workflowId === w.id} onChange={() => { setWorkflowId(w.id); setValues({}); }} />
                  <span>
                    <span className="font-medium">{w.name}</span>
                    <span className="block text-xs text-muted-foreground">{w.description || `${w.inputs.length} thing${w.inputs.length === 1 ? "" : "s"} to fill in`}</span>
                  </span>
                </label>
              ))}
            </div>
          ) : <p className="text-sm text-muted-foreground">{problem}</p>)}

          {kind === "button" && workflow && (
            <div className="space-y-2">
              <div>
                <label className="text-xs text-muted-foreground" htmlFor="guide-label">What the button says</label>
                <Input id="guide-label" value={label} placeholder={workflow.name} onChange={(e) => setLabel(e.target.value)} />
              </div>
              {sent.filter((i) => i.kind !== "record").map((i) => (
                <div key={i.name}>
                  <label className="text-xs text-muted-foreground" htmlFor={`guide-in-${i.name}`}>
                    What it sends as “{humanise(i.name)}” <span className="text-[11px]">({hint(i.type)})</span>
                  </label>
                  <Input id={`guide-in-${i.name}`} value={values[i.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [i.name]: e.target.value }))} />
                </div>
              ))}
            </div>
          )}

          {kind === "list" && (entity ? (
            <div className="space-y-2">
              <div className="space-y-1" role="radiogroup" aria-label="Kind of record">
                {refs.entities.map((e) => (
                  <label key={e.name} className={cn("flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm", entityName === e.name ? "border-primary bg-primary/5" : "border-border")}>
                    <input type="radio" name="entity" checked={entityName === e.name} onChange={() => setEntityName(e.name)} /> {e.name}
                  </label>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-muted-foreground" htmlFor="guide-title">Each row says</label>
                  <select id="guide-title" value={title} onChange={(e) => setTitle(e.target.value)} className="mt-0.5 w-full rounded-md border bg-background px-2 py-1 text-sm">
                    {fields.map((f) => <option key={f.name} value={f.name}>{f.label || humanise(f.name)}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground" htmlFor="guide-subtitle">And under it (optional)</label>
                  <select id="guide-subtitle" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} className="mt-0.5 w-full rounded-md border bg-background px-2 py-1 text-sm">
                    <option value="">Nothing</option>
                    {fields.filter((f) => f.name !== title).map((f) => <option key={f.name} value={f.name}>{f.label || humanise(f.name)}</option>)}
                  </select>
                </div>
              </div>
            </div>
          ) : <p className="text-sm text-muted-foreground">{problem}</p>)}

          {problem && kind !== "list" && refs.workflows.length > 0 && <p role="alert" className="text-sm text-red-600">{problem}</p>}
        </div>

        {summary && !problem && <p className="rounded-md bg-muted p-2 text-xs text-muted-foreground">You will get: {summary}</p>}
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" disabled={!ready} onClick={() => void onAdd(spec())}>Add it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
