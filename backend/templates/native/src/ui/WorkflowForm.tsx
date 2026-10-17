// The component kit — the two ways a screen makes something happen. Every change
// to data is a workflow the Blueprint declares, typed by its inputs
// (`@/sdk/workflows`): a form that leaves a required input out, or a button that
// passes a field the workflow does not take, does not compile. These are the
// web's `WorkflowForm` and `WorkflowButton`, same props and the same `kind`
// vocabulary, drawn natively.
//
//   <WorkflowForm workflow={workflows.createOrder}
//     fields={{
//       customerId: { label: "Customer", kind: "select", options: customers },
//       total: { label: "Total", kind: "money" },
//       note: { label: "Note", kind: "textarea" },
//       source: { value: "mobile" },                      // fixed: sent, never drawn
//     }}
//     submitLabel="Place order" redirectTo={href(pages.orders)} />
//
//   <WorkflowButton workflow={workflows.approveOrder} input={{ orderId: id }} confirm="Approve this order?">Approve</WorkflowButton>
//
// `fields` has one entry per workflow input, keyed by the input's name; every
// REQUIRED input must have one (the compiler says which is missing). A required
// input is marked, and checked before anything is sent: an empty one, a bad
// email, a date that is not a date stop at the field, in words. The workflow
// still has the last word — its rules refuse what a form lets through, and the
// refusal's own sentence is shown (see useWorkflow).
//
// kinds: text, textarea, email, tel, url, password, number, money, date, time,
// datetime, select, multiselect, tags, checkbox, switch, image, file, location.
// `render` draws one field yourself (chips, a stepper) while the form keeps the
// wiring. `groups` puts fields under headings; with `steps` one at a time, with
// Back and Next, each step checked before the next.

import * as React from "react";
import { View } from "react-native";
import { useTheme } from "../theme";
import { useWorkflow, type RunResult } from "../sdk/workflow";
import { useNav } from "../sdk/nav";
import { collectInput, type FieldKind, type FieldRule, type Option } from "../sdk/form";
import type { GeoPoint } from "../sdk/geo";
import type { Workflow } from "../sdk/workflows";
import { Text } from "./Text";
import { Button, type ButtonVariant } from "./Button";
import type { IconName } from "./Icon";
import { Dialog } from "./Sheet";
import {
  DateField, Field, FileField, ImageField, LocationField, MoneyField, MultiSelect, NumberField, SelectField, SwitchField, TagsField, TextField,
} from "./Fields";

type Json = Record<string, unknown>;

/** What a field's own control is handed when it draws itself (`render`):
 *  the form still holds the value, checks it and sends it. */
export interface FieldControl<V> {
  id: string;
  value: V | undefined;
  onChange: (value: V | undefined) => void;
  required: boolean;
}

/** How one workflow input is collected. `value` fixes it instead (the record the
 *  screen is about, the decision a button stands for) and draws nothing. `span`
 *  is the web's layout hint and is accepted and ignored: a phone has one column. */
export type FieldSpec<V> =
  | { value: V }
  | ((V extends number
      ? { label: string; span?: "full"; kind?: "number" | "money"; placeholder?: string; help?: string; min?: number; max?: number; step?: number }
      : V extends boolean
        ? { label: string; span?: "full"; kind?: "checkbox" | "switch"; help?: string }
        : V extends string[]
          ? { label: string; span?: "full"; kind: "tags" | "multiselect"; options?: Option[]; help?: string }
          : V extends GeoPoint
            ? { label: string; span?: "full"; kind: "location"; help?: string }
            : { label: string; span?: "full";
                kind?: "text" | "textarea" | "email" | "date" | "time" | "datetime" | "select" | "password" | "url" | "tel" | "image" | "file";
                accept?: string;
                options?: Option[]; placeholder?: string; help?: string })
    & { render?: (control: FieldControl<V>) => React.ReactNode });

type RequiredKeys<T> = { [K in keyof T]-?: undefined extends T[K] ? never : K }[keyof T];
type OptionalKeys<T> = { [K in keyof T]-?: undefined extends T[K] ? K : never }[keyof T];

/** One entry per input: every required input MUST have one. */
export type FieldMap<I> =
  { [K in RequiredKeys<I>]: FieldSpec<NonNullable<I[K]>> } &
  { [K in OptionalKeys<I>]?: FieldSpec<NonNullable<I[K]>> };

/** A heading over some of a form's fields — and, with `steps`, one step. */
export interface FieldGroup<I> {
  title: string;
  description?: string;
  fields: (keyof I & string)[];
}

/** The spec as the form reads it: the union above, loosened to what every kind may carry. */
type Spec = FieldRule & {
  label?: string; kind?: FieldKind; help?: string; placeholder?: string; options?: Option[]; min?: number; max?: number;
  render?: (control: FieldControl<unknown>) => React.ReactNode;
};

function Control({ name, spec, value, required, error, onChange }: {
  name: string; spec: Spec; value: unknown; required: boolean; error: string | undefined; onChange: (v: unknown) => void;
}) {
  const label = spec.label ?? name;
  const kind = spec.kind ?? "text";
  const base = { label, help: spec.help, error: error ?? null };
  if (spec.render) {
    return (
      <Field {...base} required={required}>
        {spec.render({ id: `f-${name}`, value, onChange, required })}
      </Field>
    );
  }
  switch (kind) {
    case "checkbox":
    case "switch":
      return <SwitchField label={label} help={spec.help} value={Boolean(value)} onChange={onChange} />;
    case "number":
      return <NumberField {...base} required={required} value={value as number | undefined} onChange={onChange} min={spec.min} max={spec.max} placeholder={spec.placeholder} />;
    case "money":
      return <MoneyField {...base} required={required} value={value as number | undefined} onChange={onChange} min={spec.min} max={spec.max} placeholder={spec.placeholder} />;
    case "select":
      return <SelectField {...base} required={required} value={value as string | undefined} onChange={onChange} options={spec.options ?? []} placeholder={spec.placeholder} />;
    case "multiselect":
      return <MultiSelect {...base} required={required} value={value as string[] | undefined} onChange={onChange} options={spec.options ?? []} />;
    case "tags":
      return <TagsField {...base} required={required} value={value as string[] | undefined} onChange={onChange} placeholder={spec.placeholder} />;
    case "date":
    case "time":
    case "datetime":
      return <DateField {...base} required={required} kind={kind} value={value as string | undefined} onChange={onChange} />;
    case "image":
      return <ImageField {...base} required={required} value={value as string | undefined} onChange={onChange} />;
    case "file":
      return <FileField {...base} required={required} value={value as string | undefined} onChange={onChange} />;
    case "location":
      return <LocationField {...base} required={required} value={value as GeoPoint | undefined} onChange={onChange} />;
    default:
      return <TextField {...base} required={required} kind={kind} value={value as string | undefined} onChange={onChange} placeholder={spec.placeholder} />;
  }
}

export function WorkflowForm<I extends Json>({
  workflow, fields, initial, submitLabel, submitVariant = "primary", cancelHref, redirectTo, successMessage, onDone, groups, steps = false, submitPlacement = "full",
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
  onDone?: (result: RunResult) => void;
  /** Fields under headings, in order; a field in none joins the last group. */
  groups?: FieldGroup<I>[];
  /** Show the groups one at a time, with Back and Next — a long application. */
  steps?: boolean;
  /** `full` (default): a full-width button; `end`: sized to its label. */
  submitPlacement?: "end" | "full";
}) {
  const theme = useTheme();
  const nav = useNav();
  const specs = fields as unknown as Record<string, Spec | undefined>;
  const required = React.useMemo(() => new Set(workflow.required ?? []), [workflow.required]);
  const [values, setValues] = React.useState<Record<string, unknown>>(() => ({ ...(initial ?? {}) }));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [step, setStep] = React.useState(0);
  const { run, pending, error } = useWorkflow(workflow, { redirectTo, successMessage });

  const set = (name: string, v: unknown) => {
    setValues((cur) => ({ ...cur, [name]: v }));
    setErrors((cur) => { if (!(name in cur)) return cur; const { [name]: _gone, ...rest } = cur; return rest; });
  };

  // THE GROUPS, with every field somewhere: one named in none joins the last.
  const named = new Set((groups ?? []).flatMap((g) => g.fields as string[]));
  const loose = Object.keys(specs).filter((n) => !named.has(n));
  const parts = (groups ?? []).map((g, i, all) => ({ ...g, names: [...(g.fields as string[]), ...(i === all.length - 1 ? loose : [])] }));
  const stepped = steps && parts.length > 1;
  const last = !stepped || step === parts.length - 1;

  const submit = async () => {
    const { input, errors: found } = collectInput(specs, values, required);
    if (Object.keys(found).length) {
      setErrors(found);
      // A stepped form goes back to the first step that has something to fix.
      if (stepped) setStep(Math.max(0, parts.findIndex((p) => p.names.some((n) => n in found))));
      return;
    }
    const out = await run(input as I);
    // A create form that stays put is ready for the next record; the values just
    // saved still sitting in it read as "not saved yet". A form editing a record
    // (`initial`) keeps what it now holds.
    if (out.ok && !redirectTo && !initial) { setValues({}); setErrors({}); }
    onDone?.(out);
  };

  const next = () => {
    const { errors: found } = collectInput(specs, values, required, parts[step].names);
    if (Object.keys(found).length) { setErrors(found); return; }
    setErrors({});
    setStep((s) => Math.min(s + 1, parts.length - 1));
  };

  const field = (name: string) => {
    const spec = specs[name];
    if (!spec || "value" in spec) return null;
    return (
      <Control key={name} name={name} spec={spec} value={values[name]} error={errors[name]}
        required={required.has(name) && spec.kind !== "checkbox" && spec.kind !== "switch"} onChange={(v) => set(name, v)} />
    );
  };
  const section = (g: (typeof parts)[number]) => (
    <View key={g.title} style={{ gap: theme.space.lg }}>
      <View style={{ gap: 2 }}>
        <Text variant="heading">{g.title}</Text>
        {g.description ? <Text tone="muted">{g.description}</Text> : null}
      </View>
      {g.names.map(field)}
    </View>
  );

  return (
    <View style={{ gap: theme.space.xl }}>
      {stepped ? (
        <Text variant="caption" tone="muted" accessibilityLabel={`Step ${step + 1} of ${parts.length}: ${parts[step].title}`}>
          Step {step + 1} of {parts.length}
        </Text>
      ) : null}
      {parts.length === 0 ? <View style={{ gap: theme.space.lg }}>{Object.keys(specs).map(field)}</View>
        : stepped ? section(parts[step])
        : <View style={{ gap: theme.space.xl }}>{parts.map(section)}</View>}
      {error ? (
        <View accessibilityRole="alert" style={{ backgroundColor: theme.colors.destructiveSubtle, borderRadius: theme.radii.sm, padding: theme.space.md }}>
          <Text tone="danger">{error}</Text>
        </View>
      ) : null}
      <View style={{ gap: theme.space.sm, alignItems: submitPlacement === "full" ? "stretch" : "flex-end" }}>
        <Button variant={submitVariant} fullWidth={submitPlacement === "full"} loading={pending}
          onPress={last ? () => { void submit(); } : next}>
          {last ? (submitLabel ?? workflow.name) : "Next"}
        </Button>
        {stepped && step > 0 ? <Button variant="ghost" fullWidth={submitPlacement === "full"} onPress={() => setStep((s) => Math.max(0, s - 1))}>Back</Button> : null}
        {cancelHref && !(stepped && step > 0) ? <Button variant="ghost" fullWidth={submitPlacement === "full"} onPress={() => nav.push(cancelHref)}>Cancel</Button> : null}
      </View>
    </View>
  );
}

/** A button that runs a workflow with a fixed input — Approve, Close case,
 *  Delete. `confirm` asks first, in a dialog the app owns. */
export function WorkflowButton<I extends Json>({
  workflow, input, children, variant = "primary", size = "md", icon, confirm, redirectTo, successMessage, fullWidth,
}: {
  workflow: Workflow<I>;
  input: I;
  children?: React.ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md";
  /** A glyph before the label (an `Icon` name). */
  icon?: IconName;
  confirm?: string;
  redirectTo?: string;
  successMessage?: string;
  fullWidth?: boolean;
}) {
  const { run, pending } = useWorkflow(workflow, { redirectTo, successMessage });
  const [asking, setAsking] = React.useState(false);
  const label = children ?? workflow.name;
  return (
    <>
      <Button variant={variant} size={size} icon={icon} loading={pending} fullWidth={fullWidth}
        onPress={() => { if (confirm) setAsking(true); else void run(input); }}>
        {label}
      </Button>
      {confirm ? (
        <Dialog visible={asking} message={confirm} confirmLabel={typeof label === "string" ? label : workflow.name} variant={variant}
          onCancel={() => setAsking(false)} onConfirm={() => { setAsking(false); void run(input); }} />
      ) : null}
    </>
  );
}
