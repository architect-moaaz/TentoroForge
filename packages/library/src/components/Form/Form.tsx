"use client";
import * as React from "react";
import { useContext } from "react";
import { useForm, Controller, useWatch, type SubmitHandler } from "react-hook-form";
import { DatePicker } from "../DatePicker/DatePicker";
import { RadioGroup } from "../RadioGroup/RadioGroup";
import { Switch } from "../Switch/Switch";
import { ensureHumanLabel } from "../../utils/humanizeLabel";
import {
  WorkflowDispatcherContext,
  evaluateComputed,
  computedEvalOrder,
  computeFieldConditionalStates,
  interpolate,
  runComputeAction,
  type FieldInteraction,
  type FieldConditionalState,
  type ComputeAction,
} from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";
import { fallbackDispatch } from "../../util/fallbackDispatch";
import { fallbackFetchData, type FormDataFetcher } from "../../util/fallbackFetchData";
import { runOutcome, parentPath, withDefaults } from "../../util/formOutcome";
import { hydrateFormValues, type HydrationFieldSpec } from "../../util/formValueHydration";

type FieldSpec =
  | { kind: "text" | "email" | "number"; name: string; label: string; required?: boolean; placeholder?: string }
  | { kind: "textarea"; name: string; label: string; required?: boolean; rows?: number }
  | { kind: "select"; name: string; label: string; required?: boolean; options: { value: string; label: string }[] }
  | { kind: "checkbox"; name: string; label: string }
  | { kind: "date"; name: string; label: string; required?: boolean }
  | { kind: "radio"; name: string; label: string; required?: boolean; options: { value: string; label: string }[] }
  | { kind: "switch"; name: string; label: string }
  // Typed object (for jsonb config columns): a bordered fieldset of nested typed
  // sub-fields — collected into one nested object on submit — instead of a raw
  // JSON textarea. `fields` are ordinary Field specs; names nest via dot paths.
  | { kind: "object"; name: string; label: string; description?: string; fields: Field[] }
  // Free-form string→value map (unknown shape): add/remove key+value rows.
  | { kind: "keyvalue"; name: string; label: string; description?: string; valueType?: "text" | "number" | "boolean" }
  // Spec B6: a subsection that reveals/hides a group of fields based on a
  // `visibleIf` predicate on the same form's state (feel-lite expression,
  // evaluated by the interaction engine). A section has NO submit value of
  // its own — its `fields` submit under their own names, unchanged.
  | { kind: "section"; name: string; label?: string; description?: string; visibleIf?: string; fields: Field[] };

// Every field may carry an optional `interaction` block (the field-interaction
// contract from the renderer's formInteraction engine). A field with
// `interaction.computed.formula` is a derived, read-only field whose value the
// reactive controller recomputes live from its sibling fields.
// (Intersection distributes over the union, so each variant gains `interaction`.)
type Field = FieldSpec & { interaction?: FieldInteraction };

/**
 * Slice 5 — a compute-controller exposed to any Button descendant of the
 * form. `onClick: {kind: "compute", target, formula}` reads the current
 * values via `getValues`, evaluates, and writes back via `setValue`. Null
 * outside a form (Button gracefully no-ops).
 */
export interface FormComputeController {
  getValues: () => Record<string, unknown>;
  setValue: (name: string, value: unknown) => void;
}
export const FormComputeContext = React.createContext<FormComputeController | null>(null);

const FORM_FIELD_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "space-y-3",
  comfortable: "space-y-4",
  spacious:    "space-y-6",
};

/** Post-dispatch UX descriptor. When the form's workflow succeeds or fails,
 *  the runtime uses these hints to give the user feedback — the previous
 *  behaviour ("silently re-enable the button and stay put") is what made
 *  workflow-triggered forms feel broken in generated apps. */
export type FormOutcomeAction = {
  /** Absolute URL to navigate to on this outcome. Uses window.location.href
   *  so it works in every app framework without a router dependency. */
  navigate?: string;
  /** Toast title text. When present, calls sonner's `toast.success` (or
   *  `toast.error` for the onError variant). Sonner is a peer dep of the
   *  generated app; if it isn't loadable we fall back to console.info so
   *  the library still builds standalone. */
  toast?: string;
};

type Props = {
  workflow?: string;
  fields?: Field[];
  defaultValues?: Record<string, unknown>;
  submitLabel?: string;
  /** What to do after the workflow dispatch succeeds. Default:
   *  `{ toast: "Saved", navigate: <one-level-up> }` — computed at runtime
   *  from window.location so plain schemas still get sane UX. */
  onSuccess?: FormOutcomeAction;
  /** What to do after the workflow dispatch throws. Default:
   *  `{ toast: "Couldn't save — please try again" }`. No default navigate
   *  (staying on the form lets the user correct + retry). */
  onError?: FormOutcomeAction;
  style?: StyleSlotT;
  className?: string;
  children?: React.ReactNode;
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
  /** Injectable data fetcher for dependent options / onChange populate.
   *  Defaults to the real `/api/data` loader; tests pass a mock. */
  __fetchData?: FormDataFetcher;
};

// Declarative-form control styling. The app applies Tailwind's preflight reset,
// which strips native input/button chrome — so these must carry the same token
// classes the standalone Input/Select/Button components use, or generated forms
// render as borderless inline text.
const FIELD_WRAP = "flex flex-col gap-1.5";
const FIELD_LABEL = "text-caption font-medium leading-none text-foreground";
const FIELD_CONTROL =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm " +
  "ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "disabled:cursor-not-allowed disabled:opacity-50";
const FIELD_TEXTAREA = FIELD_CONTROL.replace("h-10 ", "min-h-20 ");
const FIELD_ERROR = "text-micro text-destructive";
const FORM_SUBMIT =
  "mt-4 inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm " +
  "font-medium text-primary-foreground transition-colors hover:bg-primary/90 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "disabled:pointer-events-none disabled:opacity-50 cursor-pointer";

export function Form({ workflow, fields, defaultValues, submitLabel = "Save", onSuccess, onError, style, className, children, __dispatch, __fetchData }: Props) {
  const isDeclarative = Array.isArray(fields) && fields.length > 0;
  if (isDeclarative) {
    return (
      <DeclarativeForm
        workflow={workflow}
        fields={fields!}
        defaultValues={defaultValues}
        submitLabel={submitLabel}
        onSuccess={onSuccess}
        onError={onError}
        style={style}
        __dispatch={__dispatch}
        __fetchData={__fetchData}
      />
    );
  }

  // Container mode — render children inside a <form> wrapper. Workflow
  // dispatch is wired up if `workflow` is provided; otherwise submit is
  // a no-op preventDefault to keep custom button handlers in charge.
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  const motionProps = useMotion(style?.motion);
  const [submitting, setSubmitting] = React.useState(false);
  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!workflow || submitting) return;
    // ctxDispatch can be undefined in standalone apps where Provider/library
    // resolve different renderer copies — fall back to a direct API POST.
    const dispatch = __dispatch ?? ctxDispatch ?? fallbackDispatch;
    // Collect the values of every named control the children rendered
    // (Input/Select/Textarea forward their `name`), so the workflow receives
    // the actual form data instead of an empty object.
    const fd = new FormData(e.currentTarget as HTMLFormElement);
    const values: Record<string, unknown> = {};
    fd.forEach((v, k) => { values[k] = v; });
    setSubmitting(true);
    try {
      await dispatch(workflow, values);
      runOutcome(
        withDefaults(onSuccess, { toast: "Saved", navigate: parentPath() }),
        "success",
      );
    } catch (err) {
      runOutcome(
        withDefaults(onError, { toast: "Couldn't save — please try again" }),
        "error",
      );
      // eslint-disable-next-line no-console
      console.warn("[Form] workflow dispatch failed:", err);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form onSubmit={onSubmit} style={resolveStyle(style)} className={className} {...motionProps}>
      {children}
      {/* Container mode must still be submittable: without this button a
          section-based form (the composer's default for rich create pages)
          renders inputs with no way to dispatch — the atb0m97x upload
          form. Only when `workflow` is wired; forms driven entirely by
          custom buttons keep their no-op submit contract. */}
      {workflow ? (
        <button type="submit" disabled={submitting} aria-busy={submitting ? "true" : undefined} className={FORM_SUBMIT}>
          {submitting ? "…" : submitLabel}
        </button>
      ) : null}
    </form>
  );
}

function DeclarativeForm({
  workflow,
  fields,
  defaultValues,
  submitLabel,
  onSuccess,
  onError,
  style,
  __dispatch,
  __fetchData,
}: {
  workflow?: string;
  fields: Field[];
  defaultValues?: Record<string, unknown>;
  submitLabel: string;
  onSuccess?: FormOutcomeAction;
  onError?: FormOutcomeAction;
  style?: StyleSlotT;
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
  __fetchData?: FormDataFetcher;
}) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  // Control-type hydration — reshape the raw record (ISO date strings, UUID
  // FK ids, jsonb config columns, string booleans from postgres) into the
  // shape each control expects. Without this pass an edit form leaves
  // several fields blank because the value shape doesn't match the control.
  // Root-cause fix for B-021.6 (edit form not pre-filled) across every
  // generated app, every entity, every control type. Idempotent + additive.
  const hydratedDefaults = React.useMemo(
    () => hydrateFormValues(
      defaultValues as Record<string, unknown> | undefined,
      fields as unknown as HydrationFieldSpec[],
    ),
    [defaultValues, fields],
  );
  const { register, handleSubmit, control, setValue, getValues, unregister, reset, formState: { errors } } = useForm({ defaultValues: hydratedDefaults });
  // When defaultValues arrive AFTER first render (the record fetch resolves),
  // re-hydrate and reset form state so every control picks up its pre-fill.
  const lastDefaultsRef = React.useRef(defaultValues);
  React.useEffect(() => {
    if (defaultValues !== lastDefaultsRef.current) {
      lastDefaultsRef.current = defaultValues;
      reset(hydrateFormValues(
        defaultValues as Record<string, unknown> | undefined,
        fields as unknown as HydrationFieldSpec[],
      ));
    }
  }, [defaultValues, fields, reset]);
  const density = useDensity();
  const fetchData = __fetchData ?? fallbackFetchData;
  // Reactive computed-field layer: on any field change, recompute every
  // `interaction.computed` field (in dependency order, chains cascade in one
  // pass) and write the derived value back into the form state.
  useComputedFields(fields, control, setValue);
  // Slice 4 — conditional visibility/required/enabled/readOnly from
  // interaction predicates. Runs on every field-value change and returns
  // a per-field state map. The renderer honours visible/enabled/readOnly
  // directly and unregisters any field that turns invisible so it's
  // excluded from the submit payload.
  const conditionalStates = useConditionalFields(fields, control, unregister);
  // Business-rules layer (T2.4) — editor-authored rules that produce the
  // same visibility/required/lock hints but from a rule DSL rather than
  // a per-field predicate. Both layers are additive; downstream field
  // resolution ORs them together.
  const ruleHints = useFieldRules(modelFromWorkflow(workflow), control);
  // Dependent dropdowns: a Select with `interaction.optionsFrom.filter` /
  // `dependsOn` re-fetches its options from the data resource whenever a
  // referenced field changes. Returns the live per-field option lists.
  const dynamicOptions = useDependentOptions(fields, control, fetchData);
  // onChange populate: a field with `interaction.onChange` fetches a record when
  // its value changes and writes the fetched fields into other form fields.
  useOnChangePopulate(fields, control, setValue, fetchData);
  const [submitting, setSubmitting] = React.useState(false);
  const onSubmit: SubmitHandler<Record<string, unknown>> = async (values) => {
    if (!workflow || submitting) return;
    const dispatch = __dispatch ?? ctxDispatch ?? fallbackDispatch;
    setSubmitting(true);
    try {
      await dispatch(workflow, values);
      runOutcome(
        withDefaults(onSuccess, { toast: "Saved", navigate: parentPath() }),
        "success",
      );
    } catch (err) {
      runOutcome(
        withDefaults(onError, { toast: "Couldn't save — please try again" }),
        "error",
      );
      // eslint-disable-next-line no-console
      console.warn("[Form] workflow dispatch failed:", err);
    } finally {
      setSubmitting(false);
    }
  };
  // Slice 5 — expose a controller to child buttons so `onClick:{compute}`
  // can read the current form values + write back to a target field.
  const computeCtxValue = React.useMemo(
    () => ({ getValues: () => (getValues() ?? {}) as Record<string, unknown>, setValue }),
    [getValues, setValue],
  );
  return (
    <FormComputeContext.Provider value={computeCtxValue}>
      <form onSubmit={handleSubmit(onSubmit)} style={resolveStyle(style)} {...useMotion(style?.motion)}>
        <div className={FORM_FIELD_GAP[density]}>
          {fields.map((f) => {
            const cs = conditionalStates[f.name];
            // Hidden fields don't render — and were unregistered by
            // useConditionalFields, so they're also excluded from submit.
            // Both `conditional` (interaction predicate) and `hint`
            // (business-rule engine) reach FormFieldImpl; the field layer
            // resolves them together — either can hide/require/disable.
            if (cs && !cs.visible) return null;
            // Spec B6: a section wraps a group of fields under a header +
            // one visibleIf gate. When the gate closes, the whole group
            // disappears together (children also unregister via the
            // conditional-fields hook — their own predicates still apply).
            if ((f as { kind?: string }).kind === "section") {
              const s = f as { name: string; label?: string; description?: string; fields: Field[] };
              return (
                <fieldset key={s.name} className="flex flex-col gap-3 rounded-md border border-input p-4">
                  {(s.label || s.description) && (
                    <legend className="px-1">
                      {s.label && <span className="text-sm font-medium text-foreground">{s.label}</span>}
                      {s.description && <span className="ml-2 text-caption text-muted-foreground">{s.description}</span>}
                    </legend>
                  )}
                  {s.fields.map((cf) => {
                    const ccs = conditionalStates[cf.name];
                    if (ccs && !ccs.visible) return null;
                    return (
                      <FormFieldImpl
                        key={cf.name}
                        field={cf}
                        register={register}
                        control={control}
                        error={errors[cf.name]?.message as string | undefined}
                        optionsOverride={dynamicOptions[cf.name]}
                        conditional={ccs}
                        hint={ruleHints.get(cf.name)}
                      />
                    );
                  })}
                </fieldset>
              );
            }
            return (
              <FormFieldImpl
                key={f.name}
                field={f}
                register={register}
                control={control}
                error={errors[f.name]?.message as string | undefined}
                optionsOverride={dynamicOptions[f.name]}
                conditional={cs}
                hint={ruleHints.get(f.name)}
              />
            );
          })}
        </div>
        <button type="submit" disabled={submitting} aria-busy={submitting ? "true" : undefined} className={FORM_SUBMIT}>
          {submitting ? "…" : submitLabel}
        </button>
      </form>
    </FormComputeContext.Provider>
  );
}

/**
 * Reactive computed-field controller. On any field-value change it recomputes
 * every `interaction.computed` field, in dependency order, and writes the
 * derived value back into react-hook-form state (which drives the read-only
 * display inputs). A chained case (`subtotal → total`) cascades within a single
 * ordered pass because each computed field is evaluated against a `current` map
 * that already holds the freshly-computed values of the fields before it.
 *
 * No infinite loop: computed fields are read-only (never user-editable), the
 * pass is idempotent, and an equality guard skips the redundant `setValue` — so
 * the re-render setValue triggers finds nothing to change and settles.
 */
function useComputedFields(
  fields: Field[],
  control: ReturnType<typeof useForm>["control"],
  setValue: ReturnType<typeof useForm>["setValue"],
) {
  // Evaluation order (dep graph among computed fields; cycle-safe) + formula map.
  const order = React.useMemo(
    () => computedEvalOrder(fields.map((f) => ({ name: f.name, interaction: f.interaction }))),
    [fields],
  );
  const formulaByName = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const f of fields) {
      const formula = f.interaction?.computed?.formula;
      if (formula) m.set(f.name, formula);
    }
    return m;
  }, [fields]);

  // Watch every field so this subtree re-renders — and the effect re-runs —
  // whenever any value changes.
  const values = (useWatch({ control }) as Record<string, unknown>) ?? {};

  React.useEffect(() => {
    if (order.length === 0) return;
    const current: Record<string, unknown> = { ...values };
    for (const name of order) {
      const formula = formulaByName.get(name);
      if (formula === undefined) continue;
      const next = evaluateComputed(formula, current);
      current[name] = next; // feeds later computed fields in the SAME pass
      if (!Object.is(values[name], next)) {
        setValue(name, next as never, { shouldDirty: false, shouldValidate: false });
      }
    }
    // `values` is a fresh object each render, so this runs after every edit; the
    // equality guard makes the setValue-triggered re-run a no-op.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, order, formulaByName, setValue]);
}

/**
 * Slice 4 — reactive conditional-fields controller from interaction
 * predicates. Runs `computeFieldConditionalStates` on every field-value
 * change and returns the per-field `{visible, required, enabled,
 * readOnly}` map the renderer + submit-payload assembler read from.
 *
 * Hidden fields are ALSO unregistered from react-hook-form so they
 * disappear from the submit payload — the DOM omission alone isn't
 * enough because RHF keeps the last-known value in memory.
 */
function useConditionalFields(
  fields: Field[],
  control: ReturnType<typeof useForm>["control"],
  unregister: ReturnType<typeof useForm>["unregister"],
): Record<string, FieldConditionalState> {
  const values = (useWatch({ control }) as Record<string, unknown>) ?? {};
  // Spec B6: flatten section-kind fields so their `visibleIf` predicate
  // is evaluated by the SAME conditional-states machinery. The section
  // name gets its own entry; its child fields also register normally.
  const specs = React.useMemo(() => {
    const out: Array<{ name: string; interaction?: FieldInteraction; required?: boolean }> = [];
    const walk = (fs: Field[]) => {
      for (const f of fs) {
        if ((f as { kind?: string }).kind === "section") {
          const s = f as { name: string; visibleIf?: string; fields: Field[] };
          out.push({
            name: s.name,
            interaction: s.visibleIf ? { visibleIf: s.visibleIf } : undefined,
          });
          walk(s.fields);
        } else {
          out.push({
            name: f.name,
            interaction: f.interaction,
            required: (f as { required?: boolean }).required,
          });
        }
      }
    };
    walk(fields);
    return out;
  }, [fields]);
  const stateMap = React.useMemo(
    () => computeFieldConditionalStates(specs, values),
    [specs, values],
  );

  // Unregister any field that turned invisible this render so it
  // doesn't ride along in the submit payload. Re-registration is
  // automatic when the field mounts again.
  React.useEffect(() => {
    for (const f of fields) {
      const s = stateMap[f.name];
      if (s && !s.visible) {
        try { unregister(f.name, { keepValue: false }); } catch { /* noop */ }
      }
    }
  }, [fields, stateMap, unregister]);

  return stateMap;
}

/** Derive the entity/model name from a Create/Update workflow name. */
function modelFromWorkflow(workflow?: string): string {
  if (!workflow) return "";
  return workflow.replace(/^(Create|Update|New|Edit|Delete|Save)/i, "").trim();
}

/** Per-field outcome of the form-side business rules. */
type RuleFieldHint = { hidden?: boolean; required?: boolean; readonly?: boolean };

/**
 * Form-side business rules (visibility / required / lock). Posts the current
 * values to /api/form-rules (debounced) and returns a field→hint map. Entirely
 * fail-safe: no model, no endpoint, or any error → an empty map, so the form
 * renders exactly as if no rules existed. Value patches are applied server-side
 * on write, not here (keeps this from fighting useComputedFields).
 *
 * Coexists with `useConditionalFields` (interaction predicates): each returns
 * an independent overlay; FormFieldImpl ORs their `hidden`/`required` outputs.
 */
function useFieldRules(
  model: string,
  control: ReturnType<typeof useForm>["control"],
): Map<string, RuleFieldHint> {
  const values = (useWatch({ control }) as Record<string, unknown>) ?? {};
  const [hints, setHints] = React.useState<Map<string, RuleFieldHint>>(new Map());
  const key = React.useMemo(() => {
    try {
      return JSON.stringify(values);
    } catch {
      return "";
    }
  }, [values]);

  React.useEffect(() => {
    if (!model) return;
    let cancelled = false;
    const t = setTimeout(() => {
      fetch("/api/form-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, values }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (cancelled || !data) return;
          const m = new Map<string, RuleFieldHint>();
          for (const h of (data.formHints ?? []) as Array<RuleFieldHint & { field: string }>) {
            if (!h?.field) continue;
            m.set(h.field, { ...(m.get(h.field) ?? {}), ...h });
          }
          setHints(m);
        })
        .catch(() => {
          /* fail-safe: keep the last hints */
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, key]);

  return hints;
}

// ── Dependent options + onChange populate (S1c) ─────────────────────────────

type Option = { value: string; label: string };

/** Is a field value effectively empty (skip fetch / no dependency selected)? */
function isEmptyValue(v: unknown): boolean {
  return v === undefined || v === null || v === "";
}

/** Resolve `{{field}}` templates in a filter value against the live form values.
 *  Missing/empty refs resolve to "" so the empty-skip guard can catch them. */
function resolveFilterTemplate(tpl: unknown, values: Record<string, unknown>): string {
  if (typeof tpl !== "string") return tpl === undefined || tpl === null ? "" : String(tpl);
  return tpl.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_m, expr: string) => {
    // Support simple dotted paths; the common case is a bare field name.
    let cur: unknown = values;
    for (const part of expr.trim().split(".")) {
      if (cur && typeof cur === "object") cur = (cur as Record<string, unknown>)[part];
      else cur = undefined;
    }
    return isEmptyValue(cur) ? "" : String(cur);
  });
}

/** Map fetched rows to `{ value, label }` options (mirrors dispatch.expandOptionsFrom). */
function mapRowsToOptions(rows: unknown[], valueKey: string, labelKey: string): Option[] {
  const out: Option[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const raw = (row as Record<string, unknown>)[valueKey];
    if (raw === undefined || raw === null || raw === "") continue;
    const value = String(raw);
    const labelRaw = (row as Record<string, unknown>)[labelKey];
    const label = labelRaw === undefined || labelRaw === null || labelRaw === "" ? value : String(labelRaw);
    out.push({ value, label });
  }
  return out;
}

/**
 * Dependent-dropdown controller. For each Select field whose
 * `interaction.optionsFrom` declares a `filter` (and/or `dependsOn`), it
 * re-fetches that field's options from the data resource whenever a referenced
 * field changes, and returns the live option lists keyed by field name.
 *
 * Guards:
 *  - skips the fetch while any referenced dependency / filter value is empty
 *    (no category selected yet);
 *  - debounces redundant fetches by caching the resolved-filter key per field;
 *  - a per-field request sequence number ignores stale (out-of-order) responses.
 */
function useDependentOptions(
  fields: Field[],
  control: ReturnType<typeof useForm>["control"],
  fetchData: FormDataFetcher,
): Record<string, Option[]> {
  const dynamicFields = React.useMemo(
    () => fields.filter((f) => f.interaction?.optionsFrom?.source),
    [fields],
  );
  const values = (useWatch({ control }) as Record<string, unknown>) ?? {};
  const [options, setOptions] = React.useState<Record<string, Option[]>>({});
  const seqRef = React.useRef<Record<string, number>>({});
  const keyRef = React.useRef<Record<string, string>>({});

  React.useEffect(() => {
    for (const f of dynamicFields) {
      const of = f.interaction!.optionsFrom!;
      const rawFilter = of.filter ?? {};
      // Resolve every filter value against the current form state.
      const filter: Record<string, string> = {};
      let skip = false;
      for (const [k, tpl] of Object.entries(rawFilter)) {
        const resolved = resolveFilterTemplate(tpl, values);
        if (resolved === "") skip = true; // dependency not chosen yet
        filter[k] = resolved;
      }
      // Honour explicit dependsOn: any empty dependency also blocks the fetch.
      for (const dep of f.interaction!.dependsOn ?? []) {
        if (isEmptyValue(values[dep])) skip = true;
      }
      if (skip) continue;

      const key = JSON.stringify(filter);
      if (keyRef.current[f.name] === key) continue; // no change — debounce
      keyRef.current[f.name] = key;
      const seq = (seqRef.current[f.name] ?? 0) + 1;
      seqRef.current[f.name] = seq;

      fetchData(of.source, filter)
        .then((rows) => {
          if (seqRef.current[f.name] !== seq) return; // stale response — ignore
          setOptions((prev) => ({
            ...prev,
            [f.name]: mapRowsToOptions(Array.isArray(rows) ? rows : [], of.value, of.label),
          }));
        })
        .catch(() => {
          /* fetch failure — leave existing options unchanged */
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, dynamicFields, fetchData]);

  return options;
}

/**
 * onChange-populate controller. For each field with `interaction.onChange`,
 * when the driving field (`fetch.from`) changes to a non-empty value it fetches
 * the matching record (`resource` filtered by `by = <from value>`) and writes
 * each `set` target from the fetched result via `setValue`.
 *
 * The first effect run only records a baseline (so an edit-form's prefilled
 * value isn't clobbered on mount); thereafter real changes trigger the fetch. A
 * per-field sequence number ignores stale responses; fetch failures never throw.
 */
function useOnChangePopulate(
  fields: Field[],
  control: ReturnType<typeof useForm>["control"],
  setValue: ReturnType<typeof useForm>["setValue"],
  fetchData: FormDataFetcher,
) {
  const ocFields = React.useMemo(
    () => fields.filter((f) => f.interaction?.onChange?.fetch?.resource),
    [fields],
  );
  const values = (useWatch({ control }) as Record<string, unknown>) ?? {};
  const seqRef = React.useRef<Record<string, number>>({});
  const lastRef = React.useRef<Record<string, unknown>>({});
  const mountedRef = React.useRef(false);

  React.useEffect(() => {
    const first = !mountedRef.current;
    mountedRef.current = true;
    for (const f of ocFields) {
      const oc = f.interaction!.onChange!;
      const fromVal = values[oc.fetch.from];
      const prev = lastRef.current[f.name];
      lastRef.current[f.name] = fromVal;
      // On mount, only baseline — don't fetch (avoids clobbering edit prefill).
      if (first) continue;
      if (Object.is(prev, fromVal)) continue; // this field's driver didn't change
      if (isEmptyValue(fromVal)) continue; // cleared — nothing to populate

      const seq = (seqRef.current[f.name] ?? 0) + 1;
      seqRef.current[f.name] = seq;
      fetchData(oc.fetch.resource, { [oc.fetch.by]: String(fromVal) })
        .then((rows) => {
          if (seqRef.current[f.name] !== seq) return; // stale response — ignore
          const result = Array.isArray(rows) ? rows[0] : rows;
          if (!result || typeof result !== "object") return;
          for (const [target, tpl] of Object.entries(oc.set)) {
            const v = interpolate(String(tpl), { result });
            setValue(target, v as never, { shouldDirty: true, shouldValidate: false });
          }
        })
        .catch(() => {
          /* fetch failure — leave targets unchanged */
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, ocFields, fetchData, setValue]);
}

function FormFieldImpl({
  field,
  register,
  control,
  error,
  namePrefix = "",
  optionsOverride,
  conditional,
  hint,
}: {
  field: Field;
  register: ReturnType<typeof useForm>["register"];
  control: ReturnType<typeof useForm>["control"];
  error?: string;
  namePrefix?: string;
  optionsOverride?: Option[];
  conditional?: FieldConditionalState;
  hint?: { hidden?: boolean; required?: boolean; readonly?: boolean };
}) {
  // Form-side business rule outcomes: a rules-engine hint hiding the field
  // takes effect here too (belt + suspenders — interaction predicates were
  // already handled by the parent skip-render loop). set_required from
  // the rules engine ORs with the interaction-predicate required flag.
  if (hint?.hidden) return null;
  // Raw-key guarantee: a machine-looking label ("hire_date",
  // "instructorId") never reaches the user; deliberate copy passes
  // through untouched. Falls back to the field name when the schema
  // omitted the label entirely.
  {
    const humanLabel = ensureHumanLabel((field as { label?: string }).label ?? field.name);
    if (humanLabel !== (field as { label?: string }).label) {
      field = { ...field, label: humanLabel } as Field;
    }
  }
  // Nested object sub-fields register under a dot path (e.g. "criteria.minHeightCm")
  // so react-hook-form collects them into one nested object on submit.
  const name = namePrefix + field.name;
  const id = `field-${name}`;
  // Resolve final per-field flags. Priority (higher wins for require/read-only):
  //   1. interaction predicate result (conditional.required / .readOnly)
  //   2. rules engine hint (hint.required / hint.readonly)
  //   3. static field.required attribute
  // Either interaction OR rules can force required=true; either can force
  // read-only. `enabled` is currently interaction-only.
  const effRequired =
    (conditional?.required ?? (field as { required?: boolean }).required ?? false) ||
    !!hint?.required;
  const effDisabled = conditional ? !conditional.enabled : false;
  const effReadOnly = (conditional?.readOnly ?? false) || !!hint?.readonly;
  // Kept for downstream sites that read the merged required flag directly.
  const fieldRequired = effRequired;
  // Computed/derived field: read-only, value supplied by the reactive
  // controller (useComputedFields) via setValue. `readOnly` (not `disabled`)
  // keeps the value in the submit payload and blocks user typing.
  if (field.interaction?.computed) {
    return (
      <div className={FIELD_WRAP}>
        <label htmlFor={id} className={FIELD_LABEL}>{field.label}</label>
        <input
          id={id}
          type={field.kind === "number" ? "number" : "text"}
          className={FIELD_CONTROL + " bg-muted text-muted-foreground"}
          readOnly
          aria-readonly="true"
          data-computed="true"
          tabIndex={-1}
          {...register(name)}
        />
        {error && <p role="alert" className={FIELD_ERROR}>{error}</p>}
      </div>
    );
  }
  switch (field.kind) {
    case "text":
    case "email":
    case "number":
      return (
        <div className={FIELD_WRAP}>
          <label htmlFor={id} className={FIELD_LABEL}>{field.label}</label>
          <input
            id={id}
            type={field.kind}
            placeholder={field.placeholder}
            className={FIELD_CONTROL}
            {...register(name, {
              required: fieldRequired ? "required" : false,
              valueAsNumber: field.kind === "number",
            })}
          />
          {error && <p role="alert" className={FIELD_ERROR}>{error}</p>}
        </div>
      );
    case "textarea":
      return (
        <div className={FIELD_WRAP}>
          <label htmlFor={id} className={FIELD_LABEL}>{field.label}</label>
          <textarea
            id={id}
            rows={field.rows ?? 3}
            className={FIELD_TEXTAREA}
            {...register(name, { required: effRequired ? "required" : false })}
          />
          {error && <p role="alert" className={FIELD_ERROR}>{error}</p>}
        </div>
      );
    case "select":
      return (
        <div className={FIELD_WRAP}>
          <label htmlFor={id} className={FIELD_LABEL}>{field.label}</label>
          <select
            id={id}
            className={FIELD_CONTROL}
            {...register(name, { required: effRequired ? "required" : false })}
          >
            <option value="">—</option>
            {(optionsOverride ?? field.options).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          {error && <p role="alert" className={FIELD_ERROR}>{error}</p>}
        </div>
      );
    case "checkbox":
      return (
        <div className="flex items-center gap-2">
          <input id={id} type="checkbox" className="h-4 w-4 rounded border-input accent-primary" {...register(name)} />
          <label htmlFor={id} className="text-caption font-medium leading-none text-foreground cursor-pointer select-none">
            {field.label}
          </label>
        </div>
      );
    case "date":
      // Spec B2: real DatePicker (calendar UI, locale-aware) instead of the
      // bare `<input type="date">` that shows a browser-chrome dd/mm/yyyy box.
      return (
        <Controller name={name} control={control}
          rules={{ required: effRequired ? "required" : false }}
          render={({ field: f }) => (
            <DatePicker
              name={name}
              label={field.label}
              value={f.value ?? ""}
              onChange={f.onChange}
            />
          )} />
      );
    case "radio":
      return (
        <Controller name={name} control={control} render={({ field: f }) => (
          <RadioGroup name={name} label={field.label} options={field.options} value={f.value} onChange={f.onChange} />
        )} />
      );
    case "switch":
      return (
        <Controller name={name} control={control} render={({ field: f }) => (
          <Switch name={name} label={field.label} checked={!!f.value} onChange={f.onChange} />
        )} />
      );
    case "object":
      // Typed object — a bordered fieldset of nested typed sub-inputs. Replaces a
      // raw JSON textarea for jsonb config columns with a known shape.
      return (
        <fieldset className="rounded-md border border-input p-3">
          <legend className="px-1 text-caption font-medium text-foreground">{field.label}</legend>
          {field.description && <p className="mb-2 text-micro text-muted-foreground">{field.description}</p>}
          <div className="flex flex-col gap-2.5">
            {field.fields.map((sub) => (
              <FormFieldImpl
                key={sub.name}
                field={sub}
                register={register}
                control={control}
                namePrefix={name + "."}
              />
            ))}
          </div>
        </fieldset>
      );
    case "keyvalue":
      return <KeyValueField name={name} field={field} control={control} />;
  }
}

/** Free-form string→value map editor (add/remove rows). For jsonb columns whose
 *  shape isn't known, so users still edit structured entries, not raw JSON. */
function KeyValueField({
  name, field, control,
}: {
  name: string;
  field: Extract<Field, { kind: "keyvalue" }>;
  control: ReturnType<typeof useForm>["control"];
}) {
  const vt = field.valueType ?? "text";
  const coerce = (v: string): unknown =>
    vt === "number" ? (v === "" ? "" : Number(v)) : vt === "boolean" ? v === "true" : v;
  return (
    <Controller name={name} control={control} render={({ field: f }) => {
      const obj: Record<string, unknown> =
        f.value && typeof f.value === "object" && !Array.isArray(f.value)
          ? (f.value as Record<string, unknown>)
          : {};
      // Preserve row order + allow blank keys mid-edit by working on entries.
      const rows = Object.entries(obj);
      const commit = (next: [string, unknown][]) => {
        const out: Record<string, unknown> = {};
        for (const [k, v] of next) if (k) out[k] = v;
        f.onChange(out);
      };
      return (
        <div className={FIELD_WRAP}>
          <label className={FIELD_LABEL}>{field.label}</label>
          {field.description && <p className="text-micro text-muted-foreground">{field.description}</p>}
          <div className="flex flex-col gap-1.5">
            {rows.map(([k, v], i) => (
              <div key={i} className="flex gap-1.5">
                <input className={FIELD_CONTROL} placeholder="key" defaultValue={k}
                  onBlur={(e) => { const r = [...rows]; r[i] = [e.target.value.trim(), v]; commit(r); }} />
                <input className={FIELD_CONTROL} placeholder="value"
                  type={vt === "number" ? "number" : "text"} defaultValue={String(v ?? "")}
                  onChange={(e) => { const r = [...rows]; r[i] = [k, coerce(e.target.value)]; commit(r); }} />
                <button type="button" aria-label="Remove entry"
                  className="rounded-md border border-input px-2 text-sm hover:bg-muted"
                  onClick={() => commit(rows.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <button type="button" className="self-start text-[11px] font-medium text-primary hover:underline"
              onClick={() => commit([...rows, [`key${rows.length + 1}`, coerce("")]])}>
              + Add entry
            </button>
          </div>
        </div>
      );
    }} />
  );
}
