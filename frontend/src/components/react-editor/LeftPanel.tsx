"use client";
/**
 * The left panel: Pages, Add (the palette, COMP-001), and Layers (EDIT-003).
 * Adding is click-to-insert, or drag onto the page or a layer; guided kinds — a form, a
 * table, a workflow button — ask one thing at a time (UX-003) and insert
 * something that compiles against the app.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, ChevronDown, ChevronRight, Copy, Eye, GitBranch, GripVertical, Lock, Plus, Repeat, Search,
  Trash2, X, Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { ChartDialog } from "./ChartDialog";
import { PagesPanel } from "./PagesPanel";
import { ThemePanel } from "./ThemePanel";
import { VOID, dropPosition, moveLanding } from "./lib/drop";
import { mainRoot, plainName, plainType } from "./lib/plain";
import { checkModel, findingsByNode } from "./lib/readiness";
import { entityColumns, formImports, formJsx, tableImports, tableJsx, workflowButtonImports, workflowButtonJsx } from "./lib/templates";
import { useEditorStore, type LeftTab } from "./store";
import type { ComponentDef, ModelNode, Op, PageModel } from "./types";

/** Where an added thing goes, from what is selected: inside a container, after anything else. */
export function insertionTarget(model: PageModel, selection: string[], def: ComponentDef | null):
  { parentId: string; index: number | null; afterId?: string; why: string } {
  const root = mainRoot(model)!;
  const sel = selection[0] ? model.nodes[selection[0]] : null;
  if (!sel) return { parentId: root, index: null, why: "at the end of the page" };
  const holds = !sel.selfClosing && !VOID.has(sel.type) && (sel.kind === "element" || def?.container || ["Card", "CardContent", "CardHeader", "TabsContent", "DialogContent", "Alert"].includes(sel.type));
  if (holds && (sel.children.length || sel.kind === "element")) return { parentId: sel.id, index: null, why: `inside the selected ${plainType(sel).toLowerCase()}` };
  if (sel.parent) return { parentId: sel.parent, index: sel.index + 1, afterId: sel.id, why: `after the selected ${plainType(sel).toLowerCase()}` };
  return { parentId: root, index: null, why: "at the end of the page" };
}

export function LeftPanel({ onClose }: { onClose: () => void }) {
  const leftTab = useEditorStore((s) => s.leftTab);
  const setLeftTab = useEditorStore((s) => s.setLeftTab);
  const tabs: { key: LeftTab; label: string }[] = [{ key: "pages", label: "Pages" }, { key: "add", label: "Add" }, { key: "layers", label: "Layers" }, { key: "theme", label: "Look" }];
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center border-b border-border px-1" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={leftTab === t.key} type="button" onClick={() => setLeftTab(t.key)}
            className={cn("h-full border-b-2 px-3 text-xs font-medium", leftTab === t.key ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.label}
          </button>
        ))}
        <div className="flex-1" />
        <button type="button" className="mr-1 rounded p-1 text-muted-foreground hover:bg-muted lg:hidden" onClick={onClose} aria-label="Close panel"><X className="h-3.5 w-3.5" /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {leftTab === "pages" && <PagesPanel />}
        {leftTab === "theme" && <ThemePanel />}
        {leftTab === "add" && <AddTab />}
        {leftTab === "layers" && <LayersTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Add
// ---------------------------------------------------------------------------

function AddTab() {
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const insertJsx = useEditorStore((s) => s.insertJsx);
  const setDragComponent = useEditorStore((s) => s.setDragComponent);
  const busy = useEditorStore((s) => s.busy);
  const [q, setQ] = useState("");
  const [guide, setGuide] = useState<ComponentDef | null>(null);
  const registry = doc?.registry;
  const model = doc?.model;
  if (!registry || !model) return <p className="p-3 text-xs text-muted-foreground">Open a designed page to add things to it.</p>;

  const matches = (c: ComponentDef) => {
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return [c.label, c.description, c.category, ...c.search].some((s) => s.toLowerCase().includes(needle));
  };
  const cats = [...new Set(registry.components.map((c) => c.category))];
  const target = insertionTarget(model, selection, null);

  const add = async (c: ComponentDef) => {
    if (c.status !== "ready") return;
    if (c.guide) { setGuide(c); return; }
    const t = insertionTarget(model, selection, c);
    const imports: Op[] = c.imports.map((i) => ({ op: "addImport", source: i.source, names: i.names }));
    await insertJsx(c.jsx, imports, t.afterId ? { afterId: t.afterId, label: `Add ${c.label.toLowerCase()}` } : { parentId: t.parentId, index: t.index, label: `Add ${c.label.toLowerCase()}` });
  };

  return (
    <div className="p-2">
      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <Input className="h-8 pl-7 text-xs" placeholder="What do you want to add?" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search things to add" />
      </div>
      <p className="mb-2 px-1 text-[11px] text-muted-foreground">Click to add {target.why}. Or drag it onto the page, or onto the Layers list, to choose exactly where.</p>
      {cats.map((cat) => {
        const items = registry.components.filter((c) => c.category === cat && matches(c));
        if (!items.length) return null;
        return (
          <div key={cat} className="mb-3">
            <div className="px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{cat}</div>
            <div className="grid grid-cols-2 gap-1">
              {items.map((c) => (
                <button key={c.id} type="button" disabled={busy || c.status !== "ready"} onClick={() => void add(c)}
                  draggable={c.status === "ready"}
                  onDragStart={(e) => { e.dataTransfer.setData("application/x-forge-component", c.id); e.dataTransfer.effectAllowed = "copy"; setDragComponent(c.id); }}
                  // Later, not now: `dragend` can land before the page's drop message does.
                  onDragEnd={() => setTimeout(() => setDragComponent(null), 400)}
                  title={c.status === "ready" ? c.description : `${c.description}. Not available yet.`}
                  className={cn("flex flex-col items-start rounded-md border border-border bg-background p-2 text-left hover:border-primary/50 hover:bg-muted disabled:opacity-50",
                    c.guide && "border-dashed")}>
                  <span className="flex items-center gap-1 text-xs font-medium"><Plus className="h-3 w-3 text-muted-foreground" />{c.label}</span>
                  <span className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground">{c.description}</span>
                  {c.status !== "ready" && <span className="mt-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">Coming later</span>}
                </button>
              ))}
            </div>
          </div>
        );
      })}
      {guide && <GuideDialog def={guide} onClose={() => setGuide(null)} />}
    </div>
  );
}

/** One decision at a time; a live summary of what will be added; back and skip. */
/** Where a guided kind goes once its questions are answered: the spot it was
 *  dropped on, or — from a click in Add — the usual insertion target. */
export type DropTarget = { parentId: string; index: number | null };

export function GuideDialog({ def, target, onClose }: { def: ComponentDef; target?: DropTarget; onClose: () => void }) {
  if (def.guide === "chart" || def.guide === "metric") return <ChartDialog def={def} target={target} onClose={onClose} />;
  return <FlowDialog def={def} target={target} onClose={onClose} />;
}

function FlowDialog({ def, target, onClose }: { def: ComponentDef; target?: DropTarget; onClose: () => void }) {
  const doc = useEditorStore((s) => s.doc)!;
  const selection = useEditorStore((s) => s.selection);
  const insertJsx = useEditorStore((s) => s.insertJsx);
  const [step, setStep] = useState(0);
  const [workflowId, setWorkflowId] = useState<string>(doc.workflows.find((w) => w.launchedFrom.includes(doc.page.id))?.id ?? doc.workflows[0]?.id ?? "");
  const [label, setLabel] = useState("");
  const [dataKey, setDataKey] = useState<string>(doc.model?.loadKeys.find((k) => !k.startsWith("...")) ?? "");
  const [entityId, setEntityId] = useState<string>(doc.entities[0]?.id ?? "");
  const [columns, setColumns] = useState<string[]>([]);
  const workflow = doc.workflows.find((w) => w.id === workflowId) ?? null;
  const entity = doc.entities.find((e) => e.id === entityId) ?? null;
  const allColumns = entity ? entityColumns(entity) : [];
  useEffect(() => { setColumns(allColumns.slice(0, 5).map((c) => c.name)); }, [entityId]); // eslint-disable-line react-hooks/exhaustive-deps

  const steps: { title: string; body: React.ReactNode; ok: boolean }[] = [];
  if (def.guide === "form" || def.guide === "workflow-button") {
    steps.push({
      title: def.guide === "form" ? "What should this form save?" : "What should the button do?",
      ok: !!workflow,
      body: doc.workflows.length ? (
        <div className="space-y-1">
          {doc.workflows.map((w) => (
            <label key={w.id} className={cn("flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm", workflowId === w.id ? "border-primary bg-primary/5" : "border-border")}>
              <input type="radio" name="wf" className="mt-1" checked={workflowId === w.id} onChange={() => setWorkflowId(w.id)} />
              <span><span className="font-medium">{w.name}</span>
                <span className="block text-xs text-muted-foreground">{w.description || `${w.inputs.length} thing${w.inputs.length === 1 ? "" : "s"} to fill in`}</span></span>
            </label>
          ))}
        </div>
      ) : <p className="text-sm text-muted-foreground">This application has no workflows yet. Ask Smith to add one — for example “let people submit a request”.</p>,
    });
    if (def.guide === "workflow-button") {
      steps.push({ title: "What should the button say?", ok: true,
        body: <Input value={label} placeholder={workflow?.name ?? "Button"} onChange={(e) => setLabel(e.target.value)} aria-label="Button text" /> });
    }
  }
  if (def.guide === "table") {
    const keys = (doc.model?.loadKeys ?? []).filter((k) => !k.startsWith("..."));
    steps.push({
      title: "What should the table show?", ok: !!dataKey,
      body: keys.length ? (
        <div className="space-y-1">
          {keys.map((k) => (
            <label key={k} className={cn("flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm", dataKey === k ? "border-primary bg-primary/5" : "border-border")}>
              <input type="radio" name="dk" checked={dataKey === k} onChange={() => setDataKey(k)} /> {k}
            </label>
          ))}
          <p className="text-xs text-muted-foreground">These are what this page already loads. To show something else, ask Smith to load it.</p>
        </div>
      ) : <p className="text-sm text-muted-foreground">This page does not load a list yet. Ask Smith: “show a table of …”.</p>,
    });
    steps.push({
      title: "Which kind of record is it?", ok: !!entity,
      body: <div className="space-y-1">{doc.entities.map((e) => (
        <label key={e.id} className={cn("flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm", entityId === e.id ? "border-primary bg-primary/5" : "border-border")}>
          <input type="radio" name="ent" checked={entityId === e.id} onChange={() => setEntityId(e.id)} /> {e.name}
        </label>))}</div>,
    });
    steps.push({
      title: "Which columns?", ok: columns.length > 0,
      body: <div className="grid grid-cols-2 gap-1">{allColumns.map((c) => (
        <label key={c.name} className="flex items-center gap-2 rounded-md border border-border p-2 text-sm">
          <input type="checkbox" checked={columns.includes(c.name)} onChange={(e) => setColumns(e.target.checked ? [...columns, c.name] : columns.filter((x) => x !== c.name))} /> {c.label}
        </label>))}</div>,
    });
  }

  const preview = (() => {
    if (def.guide === "form" && workflow) return { jsx: formJsx(workflow), imports: formImports(), summary: `A form with ${workflow.inputs.length} field${workflow.inputs.length === 1 ? "" : "s"} that runs “${workflow.name}”.` };
    if (def.guide === "workflow-button" && workflow) {
      const required = workflow.inputs.filter((i) => i.required);
      return { jsx: workflowButtonJsx(workflow, { label: label || workflow.name }), imports: workflowButtonImports(),
               summary: required.length ? `A “${label || workflow.name}” button. “${workflow.name}” needs ${required.map((i) => i.name).join(", ")} — after adding it, ask Smith which record it should act on.` : `A “${label || workflow.name}” button that runs “${workflow.name}”.` };
    }
    if (def.guide === "table" && dataKey && entity) {
      const cols = allColumns.filter((c) => columns.includes(c.name));
      return { jsx: tableJsx(dataKey, cols), imports: tableImports(), summary: `A table of ${dataKey} with ${cols.map((c) => c.label).join(", ")}.` };
    }
    return null;
  })();

  const last = step >= steps.length - 1;
  const finish = async () => {
    if (!preview || !doc.model) return;
    const t = target ? { ...target, afterId: undefined } : insertionTarget(doc.model, selection, def);
    const ok = await insertJsx(preview.jsx, preview.imports, t.afterId ? { afterId: t.afterId, label: `Add ${def.label.toLowerCase()}` } : { parentId: t.parentId, index: t.index, label: `Add ${def.label.toLowerCase()}` });
    if (ok) onClose();
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{steps[step]?.title ?? def.label}</DialogTitle>
          <DialogDescription>Step {step + 1} of {steps.length} — {def.description.toLowerCase()}.</DialogDescription>
        </DialogHeader>
        <div className="max-h-[50vh] overflow-auto">{steps[step]?.body}</div>
        {preview && <p className="rounded-md bg-muted p-2 text-xs text-muted-foreground">You will get: {preview.summary}</p>}
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={() => (step ? setStep(step - 1) : onClose())}>{step ? "Back" : "Cancel"}</Button>
          <div className="flex gap-2">
            {!last && <Button size="sm" variant="outline" disabled={!steps[step]?.ok} onClick={() => setStep(step + 1)}>Next</Button>}
            <Button size="sm" disabled={!preview || !steps.every((s) => s.ok)} onClick={() => void finish()}>Add it</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

function nodeBadges(node: ModelNode, model: PageModel) {
  const out: { icon: typeof Repeat; title: string; tone?: string }[] = [];
  if (node.context === "repeat") out.push({ icon: Repeat, title: "Repeated for each record — the design of one row" });
  if (node.context === "conditional") out.push({ icon: GitBranch, title: "Shown only sometimes" });
  const acts = node.props.some((p) => ["onClick", "href", "workflow", "onSubmit"].includes(p.name)) || node.children.some((c) => model.nodes[c]?.props.some((p) => p.name === "href"));
  if (acts) out.push({ icon: Zap, title: "Does something when used" });
  return out;
}

function LayersTab() {
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const select = useEditorStore((s) => s.select);
  const hovered = useEditorStore((s) => s.hovered);
  const removeSelected = useEditorStore((s) => s.removeSelected);
  const duplicateSelected = useEditorStore((s) => s.duplicateSelected);
  const moveNode = useEditorStore((s) => s.moveNode);
  const setEditingTextId = useEditorStore((s) => s.setEditingTextId);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [q, setQ] = useState("");
  const [drop, setDrop] = useState<{ id: string; where: "before" | "after" | "inside" } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const model = doc?.model;
  const marks = useMemo(() => (doc && model ? findingsByNode(model, checkModel(doc)) : {}), [doc, model]);

  useEffect(() => {
    if (!selection.length) return;
    // Open the ancestors of the selection so it can be seen, then scroll to it.
    setCollapsed((c) => {
      const next = { ...c };
      let cur = model?.nodes[selection[0]];
      while (cur?.parent) { delete next[cur.parent]; cur = model?.nodes[cur.parent]; }
      return next;
    });
    requestAnimationFrame(() => listRef.current?.querySelector<HTMLElement>(`[data-layer="${selection[0].replace(/"/g, '\\"')}"]`)?.scrollIntoView?.({ block: "nearest" }));
  }, [selection, model]);

  if (!model) return <p className="p-3 text-xs text-muted-foreground">Open a designed page to see what is on it.</p>;
  const root = mainRoot(model)!;
  const helpers = model.roots.filter((r) => r.id !== root);

  const matches = (n: ModelNode): boolean => {
    if (!q) return true;
    const own = `${plainName(n, doc?.registry)} ${n.type}`.toLowerCase().includes(q.toLowerCase());
    return own || n.children.some((c) => matches(model.nodes[c]));
  };

  const onDrop = async (e: React.DragEvent, target: ModelNode, where: "before" | "after" | "inside") => {
    e.preventDefault();
    setDrop(null);
    const compId = e.dataTransfer.getData("application/x-forge-component");
    const movingId = e.dataTransfer.getData("application/x-forge-node");
    if (compId) {
      await useEditorStore.getState().dropComponent(compId, target.id, where);
    } else if (movingId) {
      const landing = moveLanding(model, movingId, target.id, where);
      if (landing) await moveNode(movingId, landing.parentId, landing.index);
    }
  };

  const Row = ({ id, depth }: { id: string; depth: number }) => {
    const n = model.nodes[id];
    if (!n || !matches(n)) return null;
    const isSel = selection.includes(id);
    const open = !collapsed[id];
    const badges = nodeBadges(n, model);
    return (
      <div>
        <div data-layer={id} draggable={!!n.parent}
          onDragStart={(e) => { e.dataTransfer.setData("application/x-forge-node", id); e.dataTransfer.effectAllowed = "move"; }}
          onDragOver={(e) => {
            if (!e.dataTransfer.types.some((t) => t.startsWith("application/x-forge"))) return;
            e.preventDefault();
            const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
            const y = (e.clientY - r.top) / r.height;
            setDrop({ id, where: dropPosition(n, y) });
          }}
          onDragLeave={() => setDrop((d) => (d?.id === id ? null : d))}
          onDrop={(e) => void onDrop(e, n, drop?.id === id ? drop.where : "after")}
          onClick={(e) => select([id], { extend: e.shiftKey, toggle: e.metaKey || e.ctrlKey })}
          onDoubleClick={() => { if (n.textEditable) { select([id]); setEditingTextId(id); } }}
          onMouseEnter={() => useEditorStore.getState().setHovered(id)}
          onMouseLeave={() => useEditorStore.getState().setHovered(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") { e.preventDefault(); if (n.children.length && !open) setCollapsed((c) => ({ ...c, [id]: false })); else if (n.children[0]) select([n.children[0]]); }
            if (e.key === "ArrowLeft") { e.preventDefault(); if (n.children.length && open) setCollapsed((c) => ({ ...c, [id]: true })); else if (n.parent) select([n.parent]); }
            if (e.key === "ArrowDown") { e.preventDefault(); useEditorStore.getState().selectSibling(1); }
            if (e.key === "ArrowUp") { e.preventDefault(); useEditorStore.getState().selectSibling(-1); }
            if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); void removeSelected(); }
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "d") { e.preventDefault(); void duplicateSelected(); }
            if (e.altKey && e.key === "ArrowUp" && n.parent) { e.preventDefault(); void moveNode(id, n.parent, Math.max(0, n.index - 1)); }
            if (e.altKey && e.key === "ArrowDown" && n.parent) { e.preventDefault(); void moveNode(id, n.parent, n.index + 2); }
          }}
          tabIndex={0} role="treeitem" aria-selected={isSel} aria-expanded={n.children.length ? open : undefined}
          className={cn("group relative flex h-7 cursor-pointer items-center gap-1 rounded-md pr-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-primary",
            isSel ? "bg-primary/10 text-foreground" : hovered === id ? "bg-muted" : "hover:bg-muted/60",
            drop?.id === id && drop.where === "inside" && "ring-2 ring-primary",
          )}
          style={{ paddingLeft: 6 + depth * 12 }}>
          {drop?.id === id && drop.where !== "inside" && (
            <div className={cn("pointer-events-none absolute left-2 right-2 h-0.5 bg-primary", drop.where === "before" ? "top-0" : "bottom-0")} />
          )}
          <GripVertical className="h-3 w-3 shrink-0 text-muted-foreground/40 opacity-0 group-hover:opacity-100" />
          <button type="button" className="h-4 w-4 shrink-0 text-muted-foreground" aria-label={open ? "Collapse" : "Expand"}
            onClick={(e) => { e.stopPropagation(); setCollapsed((c) => ({ ...c, [id]: open })); }} style={{ visibility: n.children.length ? "visible" : "hidden" }}>
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
          <span className="truncate">{plainName(n, doc?.registry)}</span>
          {badges.map((b) => <b.icon key={b.title} className="h-3 w-3 shrink-0 text-muted-foreground" aria-label={b.title} />)}
          {marks[id] ? <AlertCircle className="h-3 w-3 shrink-0 text-amber-500" aria-label={`${marks[id]} thing${marks[id] === 1 ? "" : "s"} to look at`} /> : null}
          <span className="flex-1" />
          {isSel && n.parent && (
            <span className="hidden gap-0.5 group-hover:flex">
              <button type="button" className="rounded p-0.5 hover:bg-background" title="Duplicate" onClick={(e) => { e.stopPropagation(); void duplicateSelected(); }}><Copy className="h-3 w-3" /></button>
              <button type="button" className="rounded p-0.5 hover:bg-background" title="Remove" onClick={(e) => { e.stopPropagation(); void removeSelected(); }}><Trash2 className="h-3 w-3" /></button>
            </span>
          )}
        </div>
        {open && n.children.map((c) => <Row key={c} id={c} depth={depth + 1} />)}
      </div>
    );
  };

  return (
    <div className="p-2" ref={listRef} role="tree" aria-label="What is on the page">
      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <Input className="h-8 pl-7 text-xs" placeholder="Find on this page" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find on this page" />
      </div>
      <Row id={root} depth={0} />
      {helpers.length > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-1 px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"><Lock className="h-3 w-3" /> Helpers on this page</div>
          {helpers.map((h) => <Row key={h.id} id={h.id} depth={0} />)}
        </div>
      )}
      <p className="mt-3 px-1 text-[11px] text-muted-foreground">Drag to reorder. Alt+↑/↓ moves the selected item. <Eye className="inline h-3 w-3" /> Double-click text to change it.</p>
    </div>
  );
}
