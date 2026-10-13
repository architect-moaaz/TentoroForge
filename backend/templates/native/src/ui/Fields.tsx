// The component kit — form fields. One per `kind` of the web's WorkflowForm, all
// with the same shape so they are interchangeable and a custom form reads like
// the generated one:
//
//   <TextField label="Title" value={v} onChange={setV} required error={err} />
//
//   label, required (asterisk), help (a line under), error (a sentence in red),
//   disabled, value / onChange. `onChange` gives the value in its own type: a
//   string, a number (undefined when cleared), a boolean, a string[], an id.
//
// TextField (text, textarea, email, tel, url, password) · NumberField · MoneyField
// (a number in major units with the app's currency symbol) · SelectField (a sheet
// of options, searchable when long) · MultiSelect (chips) · TagsField (free words)
// · SwitchField (checkbox / switch) · DateField (date, time, datetime — typed as
// 2026-03-01 / 14:30, with a Today/Now button; no native picker dependency) ·
// ImageField / FileField (camera, library, document -> uploaded, value is the
// stored id) · LocationField (the approximate position, with permission).
//
// Every control is at least 44 points tall, labelled for screen readers, and
// uses the right keyboard for what it takes.

import * as React from "react";
import { ActivityIndicator, Image, Pressable, Switch, TextInput, View, type KeyboardTypeOptions, type TextInputProps } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { Button } from "./Button";
import { Tag } from "./Display";
import { Sheet } from "./Sheet";
import { CURRENCY, } from "../sdk/money";
import { LOCALE } from "../config.generated";
import { currencySymbol, formatDate } from "../sdk/format";
import { isPoint, type GeoPoint } from "../sdk/geo";
import { nowText, numberFromText, validateValue, type Option } from "../sdk/form";
import { fileSource, pickDocument, pickImage, uploadFile, type PickedFile } from "../sdk/files";
import { askPosition } from "../sdk/location";

export type { Option };

// ---------------------------------------------------------------------------
// The shell every field sits in
// ---------------------------------------------------------------------------

export interface FieldShellProps {
  label?: string;
  required?: boolean;
  help?: string;
  error?: string | null;
  children: React.ReactNode;
}

/** The label, the control, the help line and the error: what every field shares. */
export function Field({ label, required, help, error, children }: FieldShellProps) {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.space.xs }}>
      {label ? (
        <Text variant="label">
          {label}
          {required ? <Text variant="label" tone="danger" accessibilityElementsHidden importantForAccessibility="no"> *</Text> : null}
        </Text>
      ) : null}
      {children}
      {error ? <Text variant="caption" tone="danger" accessibilityLiveRegion="polite">{error}</Text>
        : help ? <Text variant="caption" tone="muted">{help}</Text> : null}
    </View>
  );
}

interface Common {
  label?: string;
  required?: boolean;
  help?: string;
  error?: string | null;
  disabled?: boolean;
}

function useBox(error: string | null | undefined, focused: boolean, disabled?: boolean) {
  const theme = useTheme();
  return {
    minHeight: theme.touch + 4,
    borderWidth: 1,
    borderColor: error ? theme.colors.destructive : focused ? theme.colors.ring : theme.colors.input,
    borderRadius: theme.radius,
    backgroundColor: disabled ? theme.colors.muted : theme.colors.card,
    paddingHorizontal: theme.space.md,
    color: theme.colors.foreground,
    fontSize: 16,
  } as const;
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

export interface TextFieldProps extends Common {
  value: string | undefined;
  onChange: (value: string) => void;
  kind?: "text" | "textarea" | "email" | "tel" | "url" | "password";
  placeholder?: string;
  onBlur?: () => void;
}

const KEYBOARD: Record<NonNullable<TextFieldProps["kind"]>, { keyboardType: KeyboardTypeOptions; autoCapitalize: TextInputProps["autoCapitalize"]; autoComplete?: TextInputProps["autoComplete"] }> = {
  text: { keyboardType: "default", autoCapitalize: "sentences" },
  textarea: { keyboardType: "default", autoCapitalize: "sentences" },
  email: { keyboardType: "email-address", autoCapitalize: "none", autoComplete: "email" },
  tel: { keyboardType: "phone-pad", autoCapitalize: "none", autoComplete: "tel" },
  url: { keyboardType: "url", autoCapitalize: "none" },
  password: { keyboardType: "default", autoCapitalize: "none", autoComplete: "password" },
};

export function TextField({ label, required, help, error, disabled, value, onChange, kind = "text", placeholder, onBlur }: TextFieldProps) {
  const theme = useTheme();
  const [focused, setFocused] = React.useState(false);
  const box = useBox(error, focused, disabled);
  const k = KEYBOARD[kind];
  return (
    <Field label={label} required={required} help={help} error={error}>
      <TextInput
        value={value ?? ""}
        onChangeText={onChange}
        editable={!disabled}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.mutedForeground}
        accessibilityLabel={label}
        multiline={kind === "textarea"}
        secureTextEntry={kind === "password"}
        autoCorrect={kind === "text" || kind === "textarea"}
        keyboardType={k.keyboardType}
        autoCapitalize={k.autoCapitalize}
        autoComplete={k.autoComplete}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); onBlur?.(); }}
        style={[box, kind === "textarea" ? { minHeight: 110, textAlignVertical: "top", paddingTop: theme.space.md } : { paddingVertical: theme.space.sm }]}
      />
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Numbers and money
// ---------------------------------------------------------------------------

export interface NumberFieldProps extends Common {
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  min?: number;
  max?: number;
  placeholder?: string;
  /** Shown before the figure (a currency symbol). */
  prefix?: string;
}

/** The text a person is typing is kept as text ("1." and "-" are on the way to
 *  numbers); what the form receives is the number, or undefined while it is not one. */
export function NumberField({ label, required, help, error, disabled, value, onChange, min, max, placeholder, prefix }: NumberFieldProps) {
  const theme = useTheme();
  const [focused, setFocused] = React.useState(false);
  const [text, setText] = React.useState(value === undefined ? "" : String(value));
  const [local, setLocal] = React.useState<string | null>(null);
  // The form changed the value from outside (a reset after saving): follow it.
  React.useEffect(() => {
    const typed = numberFromText(text);
    if ((typed ?? undefined) !== value) setText(value === undefined ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const box = useBox(error ?? local, focused, disabled);
  const check = (n: number | undefined | null) => {
    setLocal(n === null ? "Enter a number." : validateValue({ kind: "number", label: label ?? "This", min, max }, n ?? undefined, false));
  };
  return (
    <Field label={label} required={required} help={help} error={error ?? local}>
      <View style={[box, { flexDirection: "row", alignItems: "center", gap: theme.space.xs }]}>
        {prefix ? <Text tone="muted">{prefix}</Text> : null}
        <TextInput
          value={text}
          editable={!disabled}
          keyboardType="decimal-pad"
          placeholder={placeholder}
          placeholderTextColor={theme.colors.mutedForeground}
          accessibilityLabel={label}
          onChangeText={(t) => { setText(t); const n = numberFromText(t); onChange(n === null ? undefined : n); if (local) check(n); }}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); check(numberFromText(text)); }}
          style={{ flex: 1, minHeight: theme.touch, color: theme.colors.foreground, fontSize: 16, fontVariant: ["tabular-nums"] }}
        />
      </View>
    </Field>
  );
}

/** A money field: a number in MAJOR units (12.50), shown with the app's currency
 *  symbol (or `currency`, for a record that carries its own). */
export function MoneyField({ currency = CURRENCY, ...rest }: NumberFieldProps & { currency?: string }) {
  return <NumberField {...rest} prefix={currencySymbol(currency, LOCALE)} />;
}

// ---------------------------------------------------------------------------
// Choices
// ---------------------------------------------------------------------------

export interface SelectFieldProps extends Common {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  options: Option[];
  placeholder?: string;
}

function OptionRow({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const theme = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="radio" accessibilityState={{ selected }} accessibilityLabel={label}
      style={{ minHeight: theme.touch, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: theme.space.sm }}>
      <Text weight={selected ? "semibold" : "regular"} style={{ flex: 1 }}>{label}</Text>
      {selected ? <Text tone="primary" weight="bold">✓</Text> : null}
    </Pressable>
  );
}

/** One of the options, chosen in a sheet; a long list gets a search box. */
export function SelectField({ label, required, help, error, disabled, value, onChange, options, placeholder = "Choose…" }: SelectFieldProps) {
  const theme = useTheme();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const box = useBox(error, false, disabled);
  const chosen = options.find((o) => o.value === value);
  const shown = query.trim() ? options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase())) : options;
  const close = () => { setOpen(false); setQuery(""); };
  return (
    <Field label={label} required={required} help={help} error={error}>
      <Pressable disabled={disabled} onPress={() => setOpen(true)} accessibilityRole="button"
        accessibilityLabel={`${label ?? "Choose"}: ${chosen?.label ?? "none chosen"}`}
        style={[box, { flexDirection: "row", alignItems: "center", justifyContent: "space-between" }]}>
        <Text style={{ flex: 1 }} tone={chosen ? "default" : "muted"} numberOfLines={1}>{chosen?.label ?? placeholder}</Text>
        <Text tone="muted" accessibilityElementsHidden importantForAccessibility="no">▾</Text>
      </Pressable>
      <Sheet visible={open} title={label} onClose={close}>
        {options.length > 8 ? (
          <TextInput value={query} onChangeText={setQuery} placeholder="Search" placeholderTextColor={theme.colors.mutedForeground}
            accessibilityLabel="Search options" autoCapitalize="none"
            style={{ minHeight: theme.touch, borderWidth: 1, borderColor: theme.colors.input, borderRadius: theme.radius, paddingHorizontal: theme.space.md, color: theme.colors.foreground, fontSize: 16 }} />
        ) : null}
        {!required && chosen ? <OptionRow label="Clear" selected={false} onPress={() => { onChange(undefined); close(); }} /> : null}
        {shown.map((o) => <OptionRow key={o.value} label={o.label} selected={o.value === value} onPress={() => { onChange(o.value); close(); }} />)}
        {shown.length === 0 ? <Text tone="muted">Nothing matches.</Text> : null}
      </Sheet>
    </Field>
  );
}

export interface MultiSelectProps extends Common {
  value: string[] | undefined;
  onChange: (value: string[]) => void;
  options: Option[];
}

/** Any number of the options, as chips that toggle. */
export function MultiSelect({ label, required, help, error, disabled, value, onChange, options }: MultiSelectProps) {
  const chosen = value ?? [];
  return (
    <Field label={label} required={required} help={help} error={error}>
      <View accessibilityRole="menu" style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, opacity: disabled ? 0.5 : 1 }}>
        {options.map((o) => (
          <Tag key={o.value} selected={chosen.includes(o.value)}
            onPress={disabled ? undefined : () => onChange(chosen.includes(o.value) ? chosen.filter((v) => v !== o.value) : [...chosen, o.value])}>
            {o.label}
          </Tag>
        ))}
      </View>
    </Field>
  );
}

export interface TagsFieldProps extends Common {
  value: string[] | undefined;
  onChange: (value: string[]) => void;
  placeholder?: string;
}

/** Free words, typed with commas between them. */
export function TagsField({ value, onChange, placeholder = "Comma separated", ...rest }: TagsFieldProps) {
  const [text, setText] = React.useState((value ?? []).join(", "));
  React.useEffect(() => {
    // Follow a change from outside (a reset), not the person's own typing.
    const typed = text.split(",").map((s) => s.trim()).filter(Boolean);
    if (JSON.stringify(typed) !== JSON.stringify(value ?? [])) setText((value ?? []).join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <TextField {...rest} value={text} placeholder={placeholder}
      onChange={(t) => { setText(t); onChange(t.split(",").map((s) => s.trim()).filter(Boolean)); }} />
  );
}

export interface SwitchFieldProps {
  label: string;
  help?: string;
  value: boolean | undefined;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}

export function SwitchField({ label, help, value, onChange, disabled }: SwitchFieldProps) {
  const theme = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md, minHeight: theme.touch }}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="label">{label}</Text>
        {help ? <Text variant="caption" tone="muted">{help}</Text> : null}
      </View>
      <Switch value={Boolean(value)} onValueChange={onChange} disabled={disabled} accessibilityLabel={label} accessibilityRole="switch"
        trackColor={{ false: theme.colors.border, true: theme.colors.primary }} thumbColor={theme.colors.card} />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

export interface DateFieldProps extends Common {
  value: string | undefined;
  onChange: (value: string) => void;
  kind?: "date" | "time" | "datetime";
}

const DATE_HINT = { date: "YYYY-MM-DD", time: "HH:MM", datetime: "YYYY-MM-DD HH:MM" } as const;

/** A date, a time, or both, typed as 2026-03-01 / 14:30 — the shape the app stores
 *  — and checked when the person leaves the field. The button fills in now. */
export function DateField({ label, required, help, error, disabled, value, onChange, kind = "date" }: DateFieldProps) {
  const theme = useTheme();
  const [focused, setFocused] = React.useState(false);
  const [local, setLocal] = React.useState<string | null>(null);
  const box = useBox(error ?? local, focused, disabled);
  const check = (v: string | undefined) => setLocal(validateValue({ kind, label: label ?? "This" }, v, false));
  return (
    <Field label={label} required={required} error={error ?? local}
      help={help ?? (value && kind !== "time" && validateValue({ kind }, value, false) === null
        ? formatDate(value.replace(" ", "T"), LOCALE, kind === "datetime") : undefined)}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.sm }}>
        <TextInput
          value={value ?? ""} editable={!disabled} onChangeText={(t) => { onChange(t); if (local) check(t); }}
          placeholder={DATE_HINT[kind]} placeholderTextColor={theme.colors.mutedForeground}
          keyboardType="numbers-and-punctuation" autoCapitalize="none" autoCorrect={false} accessibilityLabel={label}
          onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); check(value); }}
          style={[box, { flex: 1 }]} />
        <Button variant="outline" size="sm" disabled={disabled} onPress={() => { const v = nowText(kind); onChange(v); setLocal(null); }}>
          {kind === "date" ? "Today" : "Now"}
        </Button>
      </View>
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Pictures, files, places
// ---------------------------------------------------------------------------

export interface AttachmentFieldProps extends Common {
  /** The stored file's id: what the column holds. */
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}

/** Pick, upload at once, and hold the stored id. A pick that fails to upload stops
 *  the save with a sentence — it never saves the record without its picture. */
function useAttachment(onChange: (id: string | undefined) => void) {
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const take = React.useCallback(async (pick: () => Promise<PickedFile | null>) => {
    setProblem(null);
    try {
      const file = await pick();
      if (!file) return;
      setBusy(true);
      const out = await uploadFile(file);
      if (out.id) onChange(out.id); else setProblem(out.error);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "That could not be picked.");
    } finally {
      setBusy(false);
    }
  }, [onChange]);
  return { busy, problem, take };
}

/** A picture, from the camera or the library, with a preview. */
export function ImageField({ label, required, help, error, disabled, value, onChange }: AttachmentFieldProps) {
  const theme = useTheme();
  const { busy, problem, take } = useAttachment(onChange);
  const src = fileSource(value);
  return (
    <Field label={label} required={required} help={help} error={error ?? problem}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md, flexWrap: "wrap" }}>
        {src ? <Image source={src} accessibilityLabel={label ?? "Picture"} style={{ width: 72, height: 72, borderRadius: theme.radius, backgroundColor: theme.colors.muted }} /> : null}
        <Button variant="outline" size="sm" disabled={disabled || busy} onPress={() => { void take(() => pickImage("camera")); }}>Take photo</Button>
        <Button variant="outline" size="sm" disabled={disabled || busy} onPress={() => { void take(() => pickImage("library")); }}>{src ? "Replace" : "Choose photo"}</Button>
        {src ? <Button variant="ghost" size="sm" disabled={disabled || busy} onPress={() => onChange(undefined)}>Remove</Button> : null}
        {busy ? <ActivityIndicator color={theme.colors.primary} accessibilityLabel="Uploading" /> : null}
      </View>
    </Field>
  );
}

/** A document (a PDF, a spreadsheet), uploaded; shows that one is attached. */
export function FileField({ label, required, help, error, disabled, value, onChange }: AttachmentFieldProps) {
  const theme = useTheme();
  const { busy, problem, take } = useAttachment(onChange);
  return (
    <Field label={label} required={required} help={help} error={error ?? problem}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md, flexWrap: "wrap" }}>
        <Button variant="outline" size="sm" disabled={disabled || busy} onPress={() => { void take(pickDocument); }}>{value ? "Replace file" : "Choose file"}</Button>
        {value ? <Text variant="caption" tone="success">A file is attached.</Text> : null}
        {value ? <Button variant="ghost" size="sm" disabled={disabled || busy} onPress={() => onChange(undefined)}>Remove</Button> : null}
        {busy ? <ActivityIndicator color={theme.colors.primary} accessibilityLabel="Uploading" /> : null}
      </View>
    </Field>
  );
}

export interface LocationFieldProps extends Common {
  value: GeoPoint | undefined;
  onChange: (value: GeoPoint | undefined) => void;
}

/** The person's approximate position (about 100 m), taken with their permission.
 *  Never shown as numbers: only distances are ever shown to others. */
export function LocationField({ label, required, help, error, disabled, value, onChange }: LocationFieldProps) {
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const set = isPoint(value);
  return (
    <Field label={label} required={required} help={help ?? (set ? "Saved to about 100 m — only distances are ever shown to others." : "Only an approximate position is kept.")} error={error ?? problem}>
      <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
        <Button variant={set ? "secondary" : "outline"} size="sm" loading={busy} disabled={disabled}
          onPress={async () => {
            setBusy(true); setProblem(null);
            try { onChange(await askPosition()); } catch (e) { setProblem(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
          }}>
          {set ? "Location set — update" : "Use my current location"}
        </Button>
        {set ? <Button variant="ghost" size="sm" disabled={disabled} onPress={() => onChange(undefined)}>Clear</Button> : null}
      </View>
    </Field>
  );
}
