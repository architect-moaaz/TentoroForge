"use client";
// The app SDK — client half. How a page's `view.tsx` makes something happen:
// every change to data runs a workflow the Blueprint declares, and each one is
// typed by its inputs (`./workflows`, projected). A form that leaves a required
// input out, or a button that passes a field the workflow does not take, does
// not compile.

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { Workflow } from "./workflows";

type Json = Record<string, unknown>;

export interface RunResult {
  ok: boolean;
  /** What the workflow returned — its log, and the record it wrote if any. */
  result: Json;
  error: string | null;
}

function humanError(result: Json, status: number): string {
  const e = result.error;
  if (typeof e === "string" && e) return e;
  if (e && typeof e === "object" && typeof (e as Json).message === "string") return String((e as Json).message);
  return `Something went wrong (${status}).`;
}

/** Run a workflow from the page. The data the page shows is refreshed after
 *  it succeeds; `redirectTo` navigates instead. */
export function useWorkflow<I extends Json>(
  workflow: Workflow<I>,
  options: { successMessage?: string; redirectTo?: string; silent?: boolean } = {},
) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = React.useCallback(async (input: I): Promise<RunResult> => {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`/api/workflows/${encodeURIComponent(workflow.id)}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input }),
      });
      const result = (await res.json().catch(() => ({}))) as Json;
      const failed = !res.ok || Boolean(result.error) || result.status === "failed";
      if (failed) {
        const message = humanError(result, res.status);
        setError(message);
        if (!options.silent) toast.error(`${workflow.name} failed`, { description: message });
        return { ok: false, result, error: message };
      }
      if (!options.silent) toast.success(options.successMessage ?? `${workflow.name} — done`);
      if (options.redirectTo) router.push(options.redirectTo);
      else router.refresh();
      return { ok: true, result, error: null };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      if (!options.silent) toast.error(`${workflow.name} failed`, { description: message });
      return { ok: false, result: {}, error: message };
    } finally {
      setPending(false);
    }
  }, [workflow.id, workflow.name, options.successMessage, options.redirectTo, options.silent, router]);

  return { run, pending, error };
}

// ---------------------------------------------------------------------------
// Forms
// ---------------------------------------------------------------------------

export interface Option {
  label: string;
  value: string;
}

/** How one workflow input is collected. `value` fixes it instead (the record
 *  the page is about, the decision a button stands for) and renders nothing. */
export type FieldSpec<V> =
  | { value: V }
  | (V extends number
      ? { label: string; kind?: "number"; placeholder?: string; help?: string; min?: number; max?: number; step?: number }
      : V extends boolean
        ? { label: string; kind?: "checkbox" | "switch"; help?: string }
        : V extends string[]
          ? { label: string; kind: "tags" | "multiselect"; options?: Option[]; help?: string }
          : { label: string;
              kind?: "text" | "textarea" | "email" | "date" | "datetime" | "select" | "password" | "url" | "tel";
              options?: Option[]; placeholder?: string; help?: string });

type RequiredKeys<T> = { [K in keyof T]-?: undefined extends T[K] ? never : K }[keyof T];
type OptionalKeys<T> = { [K in keyof T]-?: undefined extends T[K] ? K : never }[keyof T];

/** One entry per input: every required input MUST have one. */
export type FieldMap<I> =
  { [K in RequiredKeys<I>]: FieldSpec<NonNullable<I[K]>> } &
  { [K in OptionalKeys<I>]?: FieldSpec<NonNullable<I[K]>> };

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background " +
  "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

function Field({ name, spec, value, onChange }: {
  name: string; spec: Exclude<FieldSpec<unknown>, { value: unknown }> & Record<string, unknown>;
  value: unknown; onChange: (v: unknown) => void;
}) {
  const id = `f-${name}`;
  const kind = (spec.kind as string | undefined) ?? "text";
  const options = (spec.options as Option[] | undefined) ?? [];
  const help = spec.help ? <p className="text-xs text-muted-foreground">{String(spec.help)}</p> : null;
  const label = <label htmlFor={id} className="text-sm font-medium leading-none">{String(spec.label)}</label>;

  if (kind === "checkbox" || kind === "switch") {
    return (
      <div className="flex items-start gap-3 sm:col-span-2">
        <input id={id} type="checkbox" className="mt-0.5 h-4 w-4 rounded border-input accent-[hsl(var(--primary))]"
          checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <div className="grid gap-1">{label}{help}</div>
      </div>
    );
  }
  let control: React.ReactNode;
  if (kind === "textarea") {
    control = <textarea id={id} rows={4} className={inputClass + " h-auto min-h-[96px]"}
      placeholder={spec.placeholder as string | undefined}
      value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  } else if (kind === "select" || kind === "multiselect") {
    control = (
      <select id={id} className={inputClass} multiple={kind === "multiselect"}
        value={(value as string | string[]) ?? (kind === "multiselect" ? [] : "")}
        onChange={(e) => onChange(kind === "multiselect"
          ? Array.from(e.target.selectedOptions).map((o) => o.value) : e.target.value)}>
        {kind === "select" && <option value="">Choose…</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (kind === "tags") {
    control = <input id={id} className={inputClass} placeholder="Comma separated"
      value={Array.isArray(value) ? (value as string[]).join(", ") : ""}
      onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
  } else if (kind === "number") {
    control = <input id={id} type="number" className={inputClass}
      min={spec.min as number | undefined} max={spec.max as number | undefined} step={(spec.step as number | undefined) ?? "any"}
      placeholder={spec.placeholder as string | undefined}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
  } else {
    const type = kind === "datetime" ? "datetime-local" : kind;
    control = <input id={id} type={type} className={inputClass}
      placeholder={spec.placeholder as string | undefined}
      value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className={"grid gap-2" + (kind === "textarea" ? " sm:col-span-2" : "")}>
      {label}{control}{help}
    </div>
  );
}

/** A form that runs a workflow. `fields` has one entry per workflow input,
 *  keyed by the input's name. */
export function WorkflowForm<I extends Json>({
  workflow, fields, initial, submitLabel, cancelHref, redirectTo, successMessage, columns = 2, className, onDone,
}: {
  workflow: Workflow<I>;
  fields: FieldMap<I>;
  /** Starting values — the record being edited. */
  initial?: Partial<I>;
  submitLabel?: string;
  cancelHref?: string;
  redirectTo?: string;
  successMessage?: string;
  columns?: 1 | 2;
  className?: string;
  onDone?: (result: RunResult) => void;
}) {
  const router = useRouter();
  const specs = fields as Record<string, Record<string, unknown>>;
  const [values, setValues] = React.useState<Record<string, unknown>>(() => ({ ...(initial ?? {}) }));
  const { run, pending, error } = useWorkflow(workflow, { redirectTo, successMessage });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const input: Record<string, unknown> = {};
    for (const [name, spec] of Object.entries(specs)) {
      if (spec && "value" in spec) input[name] = spec.value;
      else if (values[name] !== undefined && values[name] !== "") input[name] = values[name];
    }
    const out = await run(input as I);
    onDone?.(out);
  };

  return (
    <form onSubmit={submit} className={"grid gap-6 " + (className ?? "")}>
      <div className={"grid gap-5 " + (columns === 2 ? "sm:grid-cols-2" : "")}>
        {Object.entries(specs).map(([name, spec]) =>
          spec && !("value" in spec) ? (
            <Field key={name} name={name} spec={spec as never} value={values[name]}
              onChange={(v) => setValues((cur) => ({ ...cur, [name]: v }))} />
          ) : null)}
      </div>
      {error && <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      <div className="flex items-center justify-end gap-3">
        {cancelHref && (
          <button type="button" onClick={() => router.push(cancelHref)}
            className="inline-flex h-10 items-center rounded-md px-4 text-sm font-medium text-muted-foreground hover:bg-muted">
            Cancel
          </button>
        )}
        <button type="submit" disabled={pending}
          className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-60">
          {pending && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
          {submitLabel ?? workflow.name}
        </button>
      </div>
    </form>
  );
}

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  outline: "border border-input bg-background hover:bg-muted",
  ghost: "hover:bg-muted",
  danger: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
};

/** A button that runs a workflow with a fixed input — Approve, Close case,
 *  Delete. `confirm` asks first. */
export function WorkflowButton<I extends Json>({
  workflow, input, children, variant = "primary", size = "md", confirm, redirectTo, successMessage, className, title,
}: {
  workflow: Workflow<I>;
  input: I;
  children?: React.ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md";
  confirm?: string;
  redirectTo?: string;
  successMessage?: string;
  className?: string;
  title?: string;
}) {
  const { run, pending } = useWorkflow(workflow, { redirectTo, successMessage });
  return (
    <button type="button" disabled={pending} title={title}
      onClick={async () => { if (confirm && !window.confirm(confirm)) return; await run(input); }}
      className={"inline-flex items-center justify-center gap-2 rounded-md font-medium transition disabled:opacity-60 " +
        (size === "sm" ? "h-8 px-3 text-xs " : "h-10 px-4 text-sm ") + buttonVariants[variant] + " " + (className ?? "")}>
      {pending && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children ?? workflow.name}
    </button>
  );
}
