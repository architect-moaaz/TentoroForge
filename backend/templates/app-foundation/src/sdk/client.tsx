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
import { fileUrl } from "./files";
import { roundPoint, isPoint, type GeoPoint } from "./geo";

export { WidgetView, chartPropsFor, type WidgetViewData, type WidgetViewProps } from "./widget-view";
export { SignInForm, SignUpForm, useSignIn, useSignUp, signupFields, type AccountField } from "./auth";
export type { ChartSelection } from "@tentoroforge/library";
export { distanceKm, formatDistance, parseNear, type GeoPoint } from "./geo";

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
        // REFUSED is the workflow's rules saying no — its end says why, in the
        // person's words, so that sentence IS the toast. Anything else broke.
        if (!options.silent) {
          if (result.refused === true) toast.error(message);
          else toast.error(`${workflow.name} failed`, { description: message });
        }
        return { ok: false, result, error: message };
      }
      if (!options.silent) toast.success(options.successMessage ?? `${workflow.name} — done`);
      // The notification bell looks again: this run may have told someone something.
      if (typeof window !== "undefined") window.dispatchEvent(new Event("forge:workflow-done"));
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
          : V extends GeoPoint
            ? { label: string; kind: "location"; help?: string }
          : { label: string;
              kind?: "text" | "textarea" | "email" | "date" | "datetime" | "select" | "password" | "url" | "tel" | "image";
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

function Field({ name, spec, value, required, onChange }: {
  name: string; spec: Exclude<FieldSpec<unknown>, { value: unknown }> & Record<string, unknown>;
  value: unknown; required: boolean; onChange: (v: unknown) => void;
}) {
  const id = `f-${name}`;
  const kind = (spec.kind as string | undefined) ?? "text";
  const options = (spec.options as Option[] | undefined) ?? [];
  const help = spec.help ? <p className="text-xs text-muted-foreground">{String(spec.help)}</p> : null;
  // Required is the WORKFLOW's word (`workflow.required`), not the page's:
  // marked, and held by the browser before anything is sent.
  const label = (
    <label htmlFor={id} className="text-sm font-medium leading-none">
      {String(spec.label)}
      {required && <span aria-hidden="true" className="ml-0.5 text-destructive">*</span>}
    </label>
  );

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
    control = <textarea id={id} rows={4} required={required} className={inputClass + " h-auto min-h-[96px]"}
      placeholder={spec.placeholder as string | undefined}
      value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  } else if (kind === "select" || kind === "multiselect") {
    control = (
      <select id={id} required={required} className={inputClass} multiple={kind === "multiselect"}
        value={(value as string | string[]) ?? (kind === "multiselect" ? [] : "")}
        onChange={(e) => onChange(kind === "multiselect"
          ? Array.from(e.target.selectedOptions).map((o) => o.value) : e.target.value)}>
        {kind === "select" && <option value="">Choose…</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (kind === "image") {
    control = <ImageUpload id={id} required={required} value={(value as string) ?? ""} onChange={onChange} />;
  } else if (kind === "location") {
    control = <LocationInput id={id} value={value} onChange={onChange} />;
  } else if (kind === "tags") {
    control = <input id={id} required={required} className={inputClass} placeholder="Comma separated"
      value={Array.isArray(value) ? (value as string[]).join(", ") : ""}
      onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
  } else if (kind === "number") {
    control = <input id={id} type="number" required={required} className={inputClass}
      min={spec.min as number | undefined} max={spec.max as number | undefined} step={(spec.step as number | undefined) ?? "any"}
      placeholder={spec.placeholder as string | undefined}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
  } else {
    const type = kind === "datetime" ? "datetime-local" : kind;
    control = <input id={id} type={type} required={required} className={inputClass}
      placeholder={spec.placeholder as string | undefined}
      value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className={"grid gap-2" + (kind === "textarea" ? " sm:col-span-2" : "")}>
      {label}{control}{help}
    </div>
  );
}

/** Store a picked image through the app's upload route; its id, or null. */
async function storeImage(file: File): Promise<string | null> {
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await fetch("/api/files/upload", { method: "POST", body });
    const ref = res.ok ? ((await res.json()) as { id?: string }) : null;
    return ref?.id ?? null;
  } catch {
    return null;
  }
}

/** An `image` input: pick a picture, it is stored at once, and the input's
 *  value is the stored file's id — what the column holds. */
function ImageUpload({ id, required, value, onChange }: {
  id: string; required: boolean; value: string; onChange: (v: unknown) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const src = fileUrl(value);
  return (
    <div className="flex items-center gap-3">
      {src && <img src={src} alt="" className="h-16 w-16 rounded-md border object-cover" />}
      <div className="grid gap-1">
        {/* The file input only picks; the value the form sends is the id. It
            holds `required` while nothing is stored, so the browser asks. */}
        <input id={id} type="file" accept="image/*" required={required && !value} disabled={busy}
          className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setBusy(true);
            setFailed(false);
            const stored = await storeImage(file);
            setBusy(false);
            if (stored) onChange(stored); else setFailed(true);
          }} />
        {busy && <p className="text-xs text-muted-foreground">Uploading…</p>}
        {failed && <p className="text-xs text-destructive">That image could not be uploaded.</p>}
      </div>
    </div>
  );
}

/** Search by picture: pick or drop an image, and the page's `?image=` becomes
 *  its stored id, so `load` can pass `ctx.searchParams.image` to `similar()`.
 *  Shows the image being searched for, and clears it. */
/** Ask the browser where the person is, once, with their permission. */
function askPosition(): Promise<GeoPoint> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new Error("This browser cannot share a location."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(roundPoint({ lat: pos.coords.latitude, lng: pos.coords.longitude })),
      (err) => reject(new Error(err.code === err.PERMISSION_DENIED
        ? "Location permission was declined — allow it in the browser to use this."
        : "Your location could not be found — try again.")),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 600_000 },
    );
  });
}

/** A `location` input: the person's approximate position (about 100 m),
 *  taken from the browser with their permission. Never shown as numbers. */
function LocationInput({ id, value, onChange }: { id: string; value: unknown; onChange: (v: unknown) => void }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const set = isPoint(value);
  return (
    <div className="grid gap-2">
      <button id={id} type="button" disabled={busy}
        onClick={async () => {
          setBusy(true); setError(null);
          try { onChange(await askPosition()); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
          finally { setBusy(false); }
        }}
        className={"inline-flex h-10 items-center justify-center gap-2 rounded-md border px-4 text-sm font-medium transition "
          + (set ? "border-primary/40 bg-primary/5 text-primary" : "border-input bg-background hover:bg-muted")}>
        {busy ? "Finding you…" : set ? "Location set — update" : "Use my current location"}
      </button>
      <p className="text-xs text-muted-foreground">
        {set ? "Saved to about 100 m — only distances are ever shown to others." : "Only an approximate position is kept."}
      </p>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/** "Near me": sorts a page by distance from the reader. Writes `?near=` (about
 *  100 m) so load.ts reads it with `whereAmI(ctx)`; pressed again, clears it. */
export function NearMe({ label = "Near me", param = "near", className }: { label?: string; param?: string; className?: string }) {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  const [on, setOn] = React.useState(false);
  React.useEffect(() => { setOn(new URLSearchParams(window.location.search).has(param)); }, [param]);
  const go = async () => {
    const url = new URL(window.location.href);
    if (on) { url.searchParams.delete(param); router.push(url.pathname + url.search); setOn(false); return; }
    setBusy(true);
    try {
      const p = await askPosition();
      url.searchParams.set(param, `${p.lat},${p.lng}`);
      router.push(url.pathname + url.search);
      setOn(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };
  return (
    <button type="button" onClick={go} disabled={busy} aria-pressed={on}
      className={"inline-flex h-9 items-center gap-2 rounded-full border px-3 text-sm font-medium transition "
        + (on ? "border-accent bg-accent-subtle text-accent-subtle-foreground" : "border-input bg-background hover:bg-muted")
        + " " + (className ?? "")}>
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" />
      </svg>
      {busy ? "Finding you…" : label}
    </button>
  );
}

export function ImageSearch({ label = "Search by image", param = "image", className }: {
  label?: string; param?: string; className?: string;
}) {
  const router = useRouter();
  const [current, setCurrent] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const [over, setOver] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    setCurrent(new URLSearchParams(window.location.search).get(param) ?? "");
  }, [param]);
  const go = (next: string) => {
    const q = new URLSearchParams(window.location.search);
    if (next) q.set(param, next); else q.delete(param);
    setCurrent(next);
    router.replace(`${window.location.pathname}${q.toString() ? "?" + q.toString() : ""}`, { scroll: false });
  };
  const take = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setFailed(false);
    const stored = await storeImage(file);
    setBusy(false);
    if (stored) go(stored); else setFailed(true);
  };
  const src = fileUrl(current);
  return (
    <div className={"flex items-center gap-3 " + (className ?? "")}>
      {src && <img src={src} alt="The image being searched for" className="h-14 w-14 rounded-md border object-cover" />}
      <button type="button" onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files?.[0]); }}
        className={"flex flex-1 flex-col items-center justify-center gap-0.5 rounded-md border-2 border-dashed px-4 py-3 text-sm "
          + (over ? "border-primary bg-primary/5" : "border-input text-muted-foreground hover:bg-muted")}>
        <span>{busy ? "Uploading…" : current ? "Search with a different image" : label}</span>
        {failed && <span className="text-xs text-destructive">That image could not be uploaded.</span>}
      </button>
      <input ref={input} type="file" accept="image/*" className="hidden"
        onChange={(e) => take(e.target.files?.[0])} />
      {current && (
        <button type="button" onClick={() => go("")}
          className="text-sm text-muted-foreground underline-offset-2 hover:underline">Clear</button>
      )}
    </div>
  );
}

/** A form that runs a workflow. `fields` has one entry per workflow input,
 *  keyed by the input's name. */
export function WorkflowForm<I extends Json>({
  workflow, fields, initial, submitLabel, submitVariant = "primary", cancelHref, redirectTo, successMessage, columns = 2, className, onDone,
}: {
  workflow: Workflow<I>;
  fields: FieldMap<I>;
  /** Starting values — the record being edited. */
  initial?: Partial<I>;
  submitLabel?: string;
  /** `accent` when submitting is the one thing this screen is for. */
  submitVariant?: "primary" | "accent";
  cancelHref?: string;
  redirectTo?: string;
  successMessage?: string;
  columns?: 1 | 2;
  className?: string;
  onDone?: (result: RunResult) => void;
}) {
  const router = useRouter();
  const specs = fields as Record<string, Record<string, unknown>>;
  const required = new Set(workflow.required ?? []);
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
    // A create form that stays put is ready for the next record; the values
    // just saved still sitting in it read as "not saved yet". A form editing
    // a record (`initial`) keeps what it now holds.
    if (out.ok && !redirectTo && !initial) setValues({});
    onDone?.(out);
  };

  return (
    <form onSubmit={submit} className={"grid gap-6 " + (className ?? "")}>
      <div className={"grid gap-5 " + (columns === 2 ? "sm:grid-cols-2" : "")}>
        {Object.entries(specs).map(([name, spec]) =>
          spec && !("value" in spec) ? (
            <Field key={name} name={name} spec={spec as never} value={values[name]}
              required={required.has(name) && !["checkbox", "switch"].includes(String(spec.kind))}
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
          className={"inline-flex h-10 items-center gap-2 rounded-md px-5 text-sm font-medium shadow-sm transition disabled:opacity-60 "
            + (submitVariant === "accent" ? "bg-accent text-accent-foreground hover:bg-accent/90" : "bg-primary text-primary-foreground hover:bg-primary/90")}>
          {pending && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
          {submitLabel ?? workflow.name}
        </button>
      </div>
    </form>
  );
}

type ButtonVariant = "primary" | "accent" | "secondary" | "outline" | "ghost" | "danger";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
  accent: "bg-accent text-accent-foreground shadow-sm hover:bg-accent/90",
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
  // ASKED INSIDE THE PAGE, NOT BY THE BROWSER. This was `window.confirm`,
  // which a browser is free to refuse: an embedded view suppresses it, and
  // Chrome stops showing it entirely once somebody ticks "prevent this page
  // from creating additional dialogs". The call then returns false and the
  // button does nothing, with nothing on screen to say why — measured on
  // 0l133sp2, where "Approve verification" looked dead. A dialog the page
  // owns always renders, and it matches the ones beside it.
  const [asking, setAsking] = React.useState(false);
  const label = children ?? workflow.name;
  const go = async () => { setAsking(false); await run(input); };
  return (
    <>
      <button type="button" disabled={pending} title={title}
        onClick={async () => { if (confirm) { setAsking(true); return; } await run(input); }}
        className={"inline-flex items-center justify-center gap-2 rounded-md font-medium transition disabled:opacity-60 " +
          (size === "sm" ? "h-8 px-3 text-xs " : "h-10 px-4 text-sm ") + buttonVariants[variant] + " " + (className ?? "")}>
        {pending && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
        {label}
      </button>
      {asking && confirm && (
        <ConfirmDialog message={confirm} confirmLabel={label} variant={variant}
                       onCancel={() => setAsking(false)} onConfirm={go} />
      )}
    </>
  );
}

/** The question a control asks before it acts. Escape and the backdrop
 *  cancel; the confirming button takes focus, so Return answers it. */
function ConfirmDialog({ message, confirmLabel, variant, onCancel, onConfirm }: {
  message: string;
  confirmLabel: React.ReactNode;
  variant: ButtonVariant;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const confirmRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div role="dialog" aria-modal="true" aria-label={message}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="w-full max-w-sm rounded-lg bg-background p-5 shadow-lg">
        <p className="text-sm text-foreground">{message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium border border-input bg-background hover:bg-muted">
            Cancel
          </button>
          <button type="button" ref={confirmRef} onClick={onConfirm}
            className={"inline-flex h-9 items-center rounded-md px-3 text-sm font-medium " + buttonVariants[variant]}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
