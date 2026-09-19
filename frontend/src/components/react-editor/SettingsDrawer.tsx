"use client";
/**
 * The settings drawer (PROP-001): generated from what is selected. Simple
 * shows the few things a first-time user needs, in their words (UX-002);
 * Advanced adds Layout, Style, Data, Events and the source. Both write the
 * same source through the same transactions.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertCircle, ChevronRight, Copy, Sparkles, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { BREAKPOINTS, CLASS_GROUPS, GROUP_BY_KEY, effectiveValue, getVisibility, setGroupValue, setVisibility, type Visibility } from "./lib/classes";
import { breadcrumb, componentFor, plainName, plainType } from "./lib/plain";
import { checkModel } from "./lib/readiness";
import { buttonAction, buttonActionOps, pageHref } from "./lib/templates";
import { useEditorStore } from "./store";
import type { Breakpoint, ModelNode, Op, PageDoc, PropValue, SettingSpec } from "./types";

const NONE = "__none__";

function classesOf(node: ModelNode): string {
  const p = node.props.find((x) => x.name === "className");
  if (!p) return "";
  if (p.kind === "string") return p.value ?? "";
  // cn("static", …): the first literal is what the family editor touches.
  const m = /^(?:cn|clsx|twMerge)\(\s*["'`]([^"'`]*)["'`]/.exec(p.value ?? "");
  return m ? m[1] : "";
}

function classesDynamic(node: ModelNode): boolean {
  const p = node.props.find((x) => x.name === "className");
  return !!p && p.kind === "expr" && !/^(?:cn|clsx|twMerge)\(\s*["'`]/.test(p.value ?? "");
}

/** A text field that commits on blur/Enter or after a pause — one change, not one per keystroke (CANVAS-005). */
function DebouncedInput({ value, onCommit, placeholder, ariaLabel, multiline }: { value: string; onCommit: (v: string) => void; placeholder?: string; ariaLabel: string; multiline?: boolean }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (draft === value) return;
    const t = setTimeout(() => onCommit(draft), 900);
    return () => clearTimeout(t);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = () => { if (draft !== value) onCommit(draft); };
  if (multiline) {
    return <textarea className="min-h-[3.5rem] w-full rounded-md border border-input bg-background px-2 py-1 text-xs" value={draft} placeholder={placeholder} aria-label={ariaLabel}
      onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); } }} />;
  }
  return <Input className="h-8 text-xs" value={draft} placeholder={placeholder} aria-label={ariaLabel}
    onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />;
}

function Field({ label, help, children, error }: { label: string; help?: string; children: React.ReactNode; error?: string }) {
  return (
    <div className="mb-3">
      <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
      {help && <p className="mt-1 text-[10px] text-muted-foreground">{help}</p>}
      {error && <p className="mt-1 flex items-center gap-1 text-[10px] text-destructive"><AlertCircle className="h-3 w-3" />{error}</p>}
    </div>
  );
}

function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-border">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-1 px-3 py-2 text-left text-xs font-semibold" aria-expanded={open}>
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} /> {title}
      </button>
      {open && <div className="px-3 pb-2">{children}</div>}
    </div>
  );
}

export function SettingsDrawer({ onClose }: { onClose: () => void }) {
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const select = useEditorStore((s) => s.select);
  const viewLevel = useEditorStore((s) => s.viewLevel);
  const setViewLevel = useEditorStore((s) => s.setViewLevel);
  const lastFindings = useEditorStore((s) => s.lastFindings);
  const model = doc?.model;
  const nodes = useMemo(() => selection.map((id) => model?.nodes[id]).filter(Boolean) as ModelNode[], [selection, model]);
  const issues = useMemo(() => (doc ? checkModel(doc).filter((f) => f.nodeId && selection.includes(f.nodeId)) : []), [doc, selection]);

  if (!doc || !model) {
    return <Empty onClose={onClose} title="Nothing to set up yet" body="Open a designed page and click something on it." />;
  }
  if (!nodes.length) {
    return <Empty onClose={onClose} title="Nothing selected" body="Click anything on the page to change it, or choose Add to put something new on the page." />;
  }
  const node = nodes[0];
  const def = componentFor(doc.registry, node.type);
  const multi = nodes.length > 1;
  const sameType = nodes.every((n) => n.type === node.type);
  const crumbs = breadcrumb(model, node.id, doc.registry);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-border p-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{multi ? `${nodes.length} things selected` : plainName(node, doc.registry)}</div>
          {!multi && (
            <nav className="mt-0.5 flex flex-wrap items-center gap-0.5 text-[11px] text-muted-foreground" aria-label="Where this is on the page">
              {crumbs.map((c, i) => (
                <span key={c.id} className="flex items-center gap-0.5">
                  {i > 0 && <ChevronRight className="h-3 w-3" />}
                  <button type="button" className={cn("hover:underline", c.id === node.id && "font-medium text-foreground")} onClick={() => select([c.id])}>{c.label}</button>
                </span>
              ))}
            </nav>
          )}
          {multi && <div className="text-[11px] text-muted-foreground">{sameType ? `All ${plainType(node, doc.registry).toLowerCase()}s — changes apply to each` : "Different kinds — only what they share can be changed together"}</div>}
          {node.context === "repeat" && <div className="mt-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">This is the design of one row; every row follows it.</div>}
          {node.context === "conditional" && <div className="mt-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">Shown only sometimes — ask Smith to change when.</div>}
        </div>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-muted" onClick={onClose} aria-label="Close settings"><X className="h-3.5 w-3.5" /></button>
      </div>

      {(issues.length > 0 || lastFindings.length > 0) && (
        <div className="border-b border-border bg-amber-50 px-3 py-2 text-[11px] text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {lastFindings.slice(0, 2).map((f, i) => <div key={`l${i}`} className="flex gap-1"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{f.plain}</div>)}
          {issues.slice(0, 3).map((f, i) => <div key={i} className="flex gap-1"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{f.plain}</div>)}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        <SimpleSettings nodes={nodes} doc={doc} def={def} />
        {viewLevel === "advanced" ? (
          <>
            <LayoutSettings nodes={nodes} />
            <StyleSettings nodes={nodes} />
            <DataSettings node={node} doc={doc} />
            <EventSettings node={node} doc={doc} />
            <AdvancedSettings node={node} doc={doc} />
          </>
        ) : (
          <div className="px-3 py-3 text-[11px] text-muted-foreground">
            Need spacing, colours, data or what happens on click in detail?{" "}
            <button type="button" className="text-primary hover:underline" onClick={() => setViewLevel("advanced")}>Show advanced settings</button>
          </div>
        )}
      </div>
      <Actions />
    </div>
  );
}

function Empty({ title, body, onClose }: { title: string; body: string; onClose: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border p-3">
        <span className="text-sm font-semibold">Settings</span>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-muted" onClick={onClose} aria-label="Close settings"><X className="h-3.5 w-3.5" /></button>
      </div>
      <div className="p-4 text-center">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-xs text-muted-foreground">{body}</p>
      </div>
    </div>
  );
}

function Actions() {
  const removeSelected = useEditorStore((s) => s.removeSelected);
  const duplicateSelected = useEditorStore((s) => s.duplicateSelected);
  const setSmith = useEditorStore((s) => s.setSmith);
  const busy = useEditorStore((s) => s.busy);
  return (
    <div className="flex gap-1 border-t border-border p-2">
      <Button size="sm" variant="outline" className="h-7 flex-1 text-xs" disabled={busy} onClick={() => setSmith({ open: true, expanded: true })}><Sparkles className="h-3 w-3" /> Ask Smith</Button>
      <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy} onClick={() => void duplicateSelected()} title="Duplicate (⌘D)"><Copy className="h-3 w-3" /></Button>
      <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive" disabled={busy} onClick={() => void removeSelected()} title="Remove (Delete)"><Trash2 className="h-3 w-3" /></Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simple
// ---------------------------------------------------------------------------

function SimpleSettings({ nodes, doc, def }: { nodes: ModelNode[]; doc: PageDoc; def: ReturnType<typeof componentFor> }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const setText = useEditorStore((s) => s.setText);
  const node = nodes[0];
  const multi = nodes.length > 1;
  const specs = (def?.settings ?? []).filter((s) => s.section === "simple");
  const hasTextSpec = specs.some((s) => s.target.kind === "text");
  const isButton = ["Button", "button", "WorkflowButton"].includes(node.type);
  const dynamic = classesDynamic(node);

  const commitClasses = (fn: (classes: string) => string) =>
    applyOps(nodes.filter((n) => !classesDynamic(n)).map((n) => ({ op: "setClasses", id: n.id, classes: fn(classesOf(n)) }) as Op), "Change look");

  return (
    <Section title="Settings">
      {!hasTextSpec && node.textEditable && !multi && (
        <Field label="Text"><DebouncedInput value={node.text ?? ""} ariaLabel="Text" onCommit={(v) => void setText(node.id, v)} /></Field>
      )}
      {!hasTextSpec && !node.textEditable && node.text && !multi && (
        <Field label="Text" help="This text comes from data. Ask Smith to change what it shows."><Input className="h-8 text-xs" value={node.text} readOnly aria-label="Text from data" /></Field>
      )}
      {specs.map((spec) => <SettingControl key={spec.key} spec={spec} nodes={nodes} doc={doc} />)}
      {isButton && !multi && <ButtonAction node={node} doc={doc} />}
      {!multi && (
        <Field label="Show on" help={dynamic ? "This item's look is decided by code; ask Smith to change it." : undefined}>
          <Select value={getVisibility(classesOf(node))} disabled={dynamic} onValueChange={(v) => void commitClasses((c) => setVisibility(c, v as Visibility, node.type === "div" && /\bflex\b/.test(c) ? "flex" : "block"))}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All screens</SelectItem>
              <SelectItem value="wide-only">Tablets and desktops only</SelectItem>
              <SelectItem value="narrow-only">Phones only</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      )}
      {!specs.length && !node.textEditable && !isButton && (
        <p className="text-[11px] text-muted-foreground">
          {def ? "" : `This is a ${plainType(node, doc.registry).toLowerCase()}. `}To change what it shows or how it behaves, select something inside it, or ask Smith.
        </p>
      )}
      {multi && <p className="text-[11px] text-muted-foreground">Text is changed one item at a time.</p>}
    </Section>
  );
}

function SettingControl({ spec, nodes, doc }: { spec: SettingSpec; nodes: ModelNode[]; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const setText = useEditorStore((s) => s.setText);
  const node = nodes[0];
  const t = spec.target;
  const label = spec.label;

  if (t.kind === "text") {
    if (nodes.length > 1) return null;
    if (!node.textEditable) return <Field label={label} help="This text comes from data — ask Smith to change it."><Input className="h-8 text-xs" readOnly value={node.text ?? ""} aria-label={label} /></Field>;
    return <Field label={label} help={spec.help}><DebouncedInput value={node.text ?? ""} ariaLabel={label} onCommit={(v) => void setText(node.id, v)} /></Field>;
  }

  if (t.kind === "prop") {
    const prop = node.props.find((p) => p.name === t.name);
    const mixed = nodes.some((n) => (n.props.find((p) => p.name === t.name)?.value ?? null) !== (prop?.value ?? null));
    const commit = (value: PropValue | null) => applyOps(nodes.map((n) => ({ op: "setProp", id: n.id, name: t.name, value }) as Op), `Change ${label.toLowerCase()}`);
    if (prop && prop.kind === "expr" && !t.expr && !t.boolean) {
      return <Field label={label} help="Set by data on this page — ask Smith to change it."><Input className="h-8 text-xs" readOnly value={prop.value ?? ""} aria-label={label} /></Field>;
    }
    if (t.boolean || spec.control === "toggle") {
      const on = !!prop && (prop.kind === "true" || prop.value === "true");
      return (
        <Field label={label} help={spec.help}>
          <div className="flex items-center gap-2"><Switch checked={on} aria-label={label} onCheckedChange={(v) => void commit(v ? { kind: "true" } : null)} /><span className="text-xs text-muted-foreground">{mixed ? "Mixed" : on ? "Yes" : "No"}</span></div>
        </Field>
      );
    }
    if (spec.control === "select" && spec.options) {
      const current = prop?.value ?? spec.default ?? NONE;
      return (
        <Field label={label} help={spec.help}>
          <Select value={mixed ? NONE : current} onValueChange={(v) => void commit(v === NONE ? null : t.expr ? { kind: "expr", value: v } : { kind: "string", value: v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder={mixed ? "Mixed" : "Choose"} /></SelectTrigger>
            <SelectContent>
              {mixed && <SelectItem value={NONE}>Mixed</SelectItem>}
              {spec.options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      );
    }
    return (
      <Field label={label} help={spec.help}>
        <DebouncedInput value={prop?.value ?? ""} placeholder={mixed ? "Mixed" : undefined} ariaLabel={label}
          onCommit={(v) => void commit(v ? { kind: "string", value: v } : null)} />
      </Field>
    );
  }

  if (t.kind === "page") {
    const prop = node.props.find((p) => p.name === t.name);
    const current = doc.pages.find((p) => prop && (prop.value === p.route || (p.key && prop.value?.includes(`pages.${p.key}`))));
    return (
      <Field label={label} help={current?.params.length ? `“${current.name}” shows one record; which one comes from the data around this link.` : spec.help}>
        <Select value={current?.id ?? NONE} onValueChange={(v) => {
          const page = doc.pages.find((p) => p.id === v);
          if (!page) return;
          const { expr } = pageHref(page);
          void applyOps([{ op: "addImport", source: "@/sdk", names: ["pages", "href"] },
                         ...nodes.map((n) => ({ op: "setProp", id: n.id, name: t.name, value: { kind: "expr", value: expr } }) as Op)], `Open ${page.name}`);
        }}>
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder={prop ? `Somewhere else (${prop.value})` : "Choose a page"} /></SelectTrigger>
          <SelectContent>{doc.pages.map((p) => <SelectItem key={p.id} value={p.id}>{p.name} <span className="text-muted-foreground">{p.route}</span></SelectItem>)}</SelectContent>
        </Select>
      </Field>
    );
  }

  if (t.kind === "workflow") {
    const prop = node.props.find((p) => p.name === t.name);
    const current = doc.workflows.find((w) => w.key && prop?.value?.includes(`workflows.${w.key}`));
    return (
      <Field label={label} help="Changing which workflow runs also changes what it needs — ask Smith to switch it safely.">
        <Input className="h-8 text-xs" readOnly value={current?.name ?? prop?.value ?? ""} aria-label={label} />
      </Field>
    );
  }

  if (t.kind === "classGroup") {
    const g = GROUP_BY_KEY[t.group];
    if (!g) return null;
    const bp: Breakpoint = "";
    const classes = classesOf(node);
    const dynamic = classesDynamic(node);
    const eff = effectiveValue(classes, t.group, bp);
    const options = spec.options ?? g.options ?? [];
    return (
      <Field label={label} help={dynamic ? "Decided by code — ask Smith." : spec.help}>
        <Select value={eff.value ?? NONE} disabled={dynamic} onValueChange={(v) => void applyOps(
          nodes.filter((n) => !classesDynamic(n)).map((n) => ({ op: "setClasses", id: n.id, classes: setGroupValue(classesOf(n), t.group, bp, v === NONE ? null : v) }) as Op), `Change ${label.toLowerCase()}`)}>
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Default" /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Default</SelectItem>
            {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>
    );
  }
  return null;
}

/** "What happens when clicked?" — goal-based choices that rewrite the button (AC-24). */
function ButtonAction({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const setSmith = useEditorStore((s) => s.setSmith);
  const model = doc.model!;
  const action = buttonAction(node, model);
  const [choice, setChoice] = useState<string>(action.kind);
  useEffect(() => setChoice(action.kind), [action.kind, node.id]);
  const link = node.children.map((c) => model.nodes[c]).find((c) => c && (c.type === "Link" || c.type === "a"));
  const currentPage = doc.pages.find((p) => action.kind === "page" && (action.detail === p.route || (p.key && action.detail.includes(`pages.${p.key}`))));
  const currentWf = doc.workflows.find((w) => action.kind === "workflow" && w.key === action.detail);

  return (
    <>
      <Field label="What happens when clicked?">
        <Select value={choice} onValueChange={(v) => {
          setChoice(v);
          if (v === "none") void applyOps(buttonActionOps(node, { kind: "none" }), "Button does nothing");
        }}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Nothing yet</SelectItem>
            <SelectItem value="page">Opens a page</SelectItem>
            <SelectItem value="workflow">Runs a workflow (save, approve, delete…)</SelectItem>
            {action.kind === "custom" && <SelectItem value="custom">{action.detail}</SelectItem>}
          </SelectContent>
        </Select>
      </Field>
      {choice === "page" && (
        <Field label="Which page?" help={currentPage?.params.length ? "This page shows one record — ask Smith which record the button should open." : undefined}>
          <Select value={currentPage?.id ?? NONE} onValueChange={(v) => {
            const page = doc.pages.find((p) => p.id === v);
            if (!page) return;
            if (link) {
              const { expr } = pageHref(page);
              void applyOps([{ op: "addImport", source: "@/sdk", names: ["pages", "href"] }, { op: "setProp", id: link.id, name: "href", value: { kind: "expr", value: expr } }], `Open ${page.name}`);
            } else {
              void applyOps(buttonActionOps(node, { kind: "page", page }), `Button opens ${page.name}`);
            }
          }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Choose a page" /></SelectTrigger>
            <SelectContent>{doc.pages.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      )}
      {choice === "workflow" && (
        <Field label="Which workflow?" help={currentWf?.inputs.some((i) => i.required) ? `“${currentWf.name}” needs ${currentWf.inputs.filter((i) => i.required).map((i) => i.name).join(", ")}. Ask Smith which record it should act on.` : undefined}>
          <Select value={currentWf?.id ?? NONE} onValueChange={(v) => {
            const wf = doc.workflows.find((w) => w.id === v);
            if (!wf) return;
            void applyOps(buttonActionOps(node, { kind: "workflow", workflow: wf }), `Button runs ${wf.name}`);
          }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Choose a workflow" /></SelectTrigger>
            <SelectContent>{doc.workflows.map((w) => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}</SelectContent>
          </Select>
          {!doc.workflows.length && <p className="mt-1 text-[10px] text-muted-foreground">No workflows yet — ask Smith to add one.</p>}
        </Field>
      )}
      {choice === "custom" && (
        <p className="mb-3 text-[11px] text-muted-foreground">This button runs something written for this page. <button type="button" className="text-primary hover:underline" onClick={() => setSmith({ open: true, expanded: true, prompt: "Explain what this button does and " })}>Ask Smith about it</button>.</p>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Advanced: Layout & Style (class families, per breakpoint)
// ---------------------------------------------------------------------------

function ClassFamilyEditor({ nodes, groups }: { nodes: ModelNode[]; groups: string[] }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const frameWidth = useEditorStore((s) => s.frameWidth);
  const width = frameWidth();
  const [bp, setBp] = useState<Breakpoint>("");
  const node = nodes[0];
  const dynamic = classesDynamic(node);
  const classes = classesOf(node);
  return (
    <>
      <Field label="Screen size" help="Values set here apply from this size up; smaller screens keep the value for all screens.">
        <Select value={bp || "base"} onValueChange={(v) => setBp(v === "base" ? "" : v as Breakpoint)}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{BREAKPOINTS.map((b) => <SelectItem key={b.key || "base"} value={b.key || "base"}>{b.label}{b.minWidth <= width && (BREAKPOINTS.filter((x) => x.minWidth <= width).slice(-1)[0]?.key === b.key) ? " · current" : ""}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      {dynamic && <p className="mb-2 text-[11px] text-muted-foreground">This item's look is decided by code at runtime, so it cannot be restyled here — ask Smith.</p>}
      {groups.map((key) => {
        const g = GROUP_BY_KEY[key];
        const eff = effectiveValue(classes, key, bp);
        const overridden = eff.from === bp && bp !== "";
        const inherited = bp !== "" && eff.value != null && eff.from !== bp;
        return (
          <Field key={key} label={g.label} help={overridden ? "Set for this screen size" : inherited ? `Inherited from ${BREAKPOINTS.find((b) => b.key === eff.from)?.label.toLowerCase()}` : undefined}>
            <div className="flex gap-1">
              <Select value={eff.value ?? NONE} disabled={dynamic} onValueChange={(v) => void applyOps(
                nodes.filter((n) => !classesDynamic(n)).map((n) => ({ op: "setClasses", id: n.id, classes: setGroupValue(classesOf(n), key, bp, v === NONE ? null : v) }) as Op), `Change ${g.label.toLowerCase()}`)}>
                <SelectTrigger className={cn("h-8 flex-1 text-xs", inherited && "text-muted-foreground")}><SelectValue placeholder="Default" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Default</SelectItem>
                  {(g.options ?? []).map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
              {overridden && <Button size="sm" variant="ghost" className="h-8 px-2 text-[10px]" title="Remove this screen size's value" onClick={() => void applyOps(
                nodes.map((n) => ({ op: "setClasses", id: n.id, classes: setGroupValue(classesOf(n), key, bp, null) }) as Op), `Reset ${g.label.toLowerCase()}`)}>Reset</Button>}
            </div>
          </Field>
        );
      })}
    </>
  );
}

function LayoutSettings({ nodes }: { nodes: ModelNode[] }) {
  return <Section title="Layout" defaultOpen={false}><ClassFamilyEditor nodes={nodes} groups={["display", "flexDirection", "flexWrap", "justify", "items", "gridCols", "gap", "spaceY", "padding", "paddingX", "paddingY", "marginTop", "marginBottom", "width", "maxWidth", "height"]} /></Section>;
}

function StyleSettings({ nodes }: { nodes: ModelNode[] }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const node = nodes[0];
  return (
    <Section title="Style" defaultOpen={false}>
      <ClassFamilyEditor nodes={nodes} groups={["textSize", "fontWeight", "textColor", "textAlign", "background", "rounded", "border", "shadow"]} />
      {nodes.length === 1 && !classesDynamic(node) && (
        <Field label="All style classes" help="Tailwind classes, for people who know them.">
          <DebouncedInput multiline value={classesOf(node)} ariaLabel="Style classes" onCommit={(v) => void applyOps([{ op: "setClasses", id: node.id, classes: v }], "Change classes")} />
        </Field>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Advanced: Data, Events, Advanced
// ---------------------------------------------------------------------------

function DataSettings({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const setSmith = useEditorStore((s) => s.setSmith);
  const exprs = node.props.filter((p) => p.kind === "expr" && !/^on[A-Z]/.test(p.name));
  const loadKeys = doc.model?.loadKeys ?? [];
  return (
    <Section title="Data" defaultOpen={false}>
      <p className="mb-2 text-[11px] text-muted-foreground">This page loads: {loadKeys.length ? loadKeys.join(", ") : "nothing"}.</p>
      {node.text && !node.textEditable && <Field label="Shows"><Input className="h-8 font-mono text-[11px]" readOnly value={node.text} aria-label="Shows" /></Field>}
      {exprs.map((p) => <Field key={p.name} label={p.name}><Input className="h-8 font-mono text-[11px]" readOnly value={p.value ?? ""} aria-label={p.name} /></Field>)}
      {!exprs.length && node.textEditable && <p className="text-[11px] text-muted-foreground">Nothing here is connected to data.</p>}
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setSmith({ open: true, expanded: true, prompt: "Connect this to " })}><Sparkles className="h-3 w-3" /> Connect data with Smith</Button>
    </Section>
  );
}

function EventSettings({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const setSmith = useEditorStore((s) => s.setSmith);
  const handlers = node.props.filter((p) => /^on[A-Z]/.test(p.name));
  const def = componentFor(doc.registry, node.type);
  return (
    <Section title="What happens when…" defaultOpen={false}>
      {handlers.map((p) => <Field key={p.name} label={p.name.replace(/^on/, "On ").toLowerCase()}><Input className="h-8 font-mono text-[11px]" readOnly value={p.value ?? ""} aria-label={p.name} /></Field>)}
      {node.type === "WorkflowButton" && <p className="mb-2 text-[11px] text-muted-foreground">Runs {node.props.find((p) => p.name === "workflow")?.value?.replace("workflows.", "") ?? "a workflow"} with {node.props.find((p) => p.name === "input")?.value ?? "no input"}.</p>}
      {node.type === "WorkflowForm" && <p className="mb-2 text-[11px] text-muted-foreground">Submitting runs {node.props.find((p) => p.name === "workflow")?.value?.replace("workflows.", "") ?? "a workflow"} with the fields' values.</p>}
      {!handlers.length && !["WorkflowButton", "WorkflowForm"].includes(node.type) && <p className="mb-2 text-[11px] text-muted-foreground">{def?.events.length ? "Nothing happens yet." : "This does not respond to clicks."}</p>}
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setSmith({ open: true, expanded: true, prompt: "When this is used, " })}><Sparkles className="h-3 w-3" /> Describe the behaviour to Smith</Button>
    </Section>
  );
}

function AdvancedSettings({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const setShowCode = useEditorStore((s) => s.setShowCode);
  const [newName, setNewName] = useState("");
  return (
    <Section title="Advanced" defaultOpen={false}>
      <div className="mb-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px]">
        <span className="text-muted-foreground">Kind</span><span className="font-mono">{node.type}</span>
        <span className="text-muted-foreground">Id</span><span className="font-mono">{node.id}</span>
        <span className="text-muted-foreground">Source</span>
        <button type="button" className="text-left font-mono text-primary hover:underline" onClick={() => setShowCode(true)}>{doc.page.file ?? "view.tsx"}:{node.line}</button>
      </div>
      {node.props.filter((p) => p.kind !== "spread").map((p) => (
        <Field key={p.name} label={p.name}>
          <div className="flex gap-1">
            {p.kind === "true" ? <Input className="h-8 text-xs" readOnly value="on" aria-label={p.name} /> : (
              <DebouncedInput value={p.value ?? ""} ariaLabel={p.name} onCommit={(v) => void applyOps([{ op: "setProp", id: node.id, name: p.name, value: p.kind === "string" ? { kind: "string", value: v } : { kind: "expr", value: v } }], `Change ${p.name}`)} />
            )}
            <Button size="sm" variant="ghost" className="h-8 px-2" title="Remove this setting" onClick={() => void applyOps([{ op: "setProp", id: node.id, name: p.name, value: null }], `Remove ${p.name}`)}><X className="h-3 w-3" /></Button>
          </div>
        </Field>
      ))}
      <Field label="Add a setting" help="name=value, as the component takes it. Checked before it is saved.">
        <Input className="h-8 text-xs" placeholder='e.g. title="Open" or disabled' value={newName} aria-label="Add a setting" onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" || !newName.trim()) return;
            const m = /^([\w-]+)(?:=(.*))?$/.exec(newName.trim());
            if (!m) return;
            const raw = m[2];
            const value: PropValue = raw === undefined ? { kind: "true" } : /^".*"$/.test(raw) ? { kind: "string", value: raw.slice(1, -1) } : /^\{.*\}$/.test(raw) ? { kind: "expr", value: raw.slice(1, -1) } : { kind: "string", value: raw };
            void applyOps([{ op: "setProp", id: node.id, name: m[1], value }], `Set ${m[1]}`);
            setNewName("");
          }} />
      </Field>
    </Section>
  );
}

export { CLASS_GROUPS };
