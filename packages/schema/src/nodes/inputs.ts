import { z } from "zod";
import { StyleSlot } from "../style-slot";

const Validators = z.object({
  required: z.boolean().optional(),
  min:      z.number().optional(),
  max:      z.number().optional(),
  pattern:  z.string().optional(),
  message:  z.string().optional(),
}).strict();

// baseField shape — every input node has these fields. Inlined into each
// node to keep zod types narrow per-node.
const baseField = {
  name:       z.string().min(1),
  label:      z.string().min(1),
  bind:       z.string().optional(),
  validators: Validators.optional(),
};

export const InputNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Input"),
  props: z.object({
    ...baseField,
    type: z.enum(["text", "email", "password", "number", "url", "tel"]),
    placeholder: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type InputNodeT = z.infer<typeof InputNode>;

const SelectOption = z.object({
  value: z.string().min(1),
  label: z.string().min(1),
}).strict();

// Dynamic-options binding for relational dropdowns. When present, the renderer
// builds the option list from a page dataSource at render time — `source` names
// the dataSource (e.g. "projects"), `value`/`label` are the item fields used for
// each option's value/label (default id/name). The static `options` array is kept
// as the fallback shown when the source is missing/empty. This is what turns a
// Task→Project FK into a real list of selectable projects instead of one
// hard-coded `{{projects[0].id}}` entry.
const OptionsFrom = z.object({
  source: z.string().min(1),
  value:  z.string().min(1).default("id"),
  label:  z.string().min(1).default("name"),
}).strict();

export const SelectNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Select"),
  props: z.object({
    ...baseField,
    options: z.array(SelectOption).min(1),
    optionsFrom: OptionsFrom.optional(),
    // Inline-add for FK dropdowns — when optionsFrom returns zero rows and
    // the referenced entity has a create route, render "+ Add new <X>"
    // instead of a dead-end empty dropdown. General capability across every
    // FK Select in every generated app. Root-cause UX for B-021.8 class.
    inlineAdd: z.object({
      route: z.string(),        // where the create form lives, e.g. "/nursery-locations/new"
      label: z.string().optional(),  // "+ Add new nursery location" — auto-derived when omitted
    }).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SelectNodeT = z.infer<typeof SelectNode>;

export const TextareaNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Textarea"),
  props: z.object({
    ...baseField,
    rows: z.number().int().positive().default(4),
    placeholder: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TextareaNodeT = z.infer<typeof TextareaNode>;

export const CheckboxNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Checkbox"),
  props: z.object({
    ...baseField,
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CheckboxNodeT = z.infer<typeof CheckboxNode>;

export const DatePickerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("DatePicker"),
  props: z.object({
    ...baseField,
    min: z.string().optional(),
    max: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type DatePickerNodeT = z.infer<typeof DatePickerNode>;

export const SwitchNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Switch"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().min(1),
    checked:  z.boolean().optional(),
    disabled: z.boolean().optional(),
    size:     z.enum(["sm", "md"]).optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SwitchNodeT = z.infer<typeof SwitchNode>;

export const NumberInputNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("NumberInput"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().min(1),
    min:      z.number().optional(),
    max:      z.number().optional(),
    step:     z.number().optional(),
    prefix:   z.string().optional(),
    suffix:   z.string().optional(),
    disabled: z.boolean().optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type NumberInputNodeT = z.infer<typeof NumberInputNode>;

const RadioOption = z.object({ value: z.string().min(1), label: z.string().min(1), disabled: z.boolean().optional() }).strict();
export const RadioGroupNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("RadioGroup"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    options:     z.array(RadioOption).min(1),
    orientation: z.enum(["vertical", "horizontal"]).optional(),
    required:    z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type RadioGroupNodeT = z.infer<typeof RadioGroupNode>;

export const SliderNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Slider"),
  props: z.object({
    name:      z.string().min(1),
    label:     z.string().optional(),
    min:       z.number().optional(),
    max:       z.number().optional(),
    step:      z.number().optional(),
    range:     z.boolean().optional(),
    showValue: z.boolean().optional(),
    bind:      z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SliderNodeT = z.infer<typeof SliderNode>;

export const FileUploadNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("FileUpload"),
  props: z.object({
    name:      z.string().min(1),
    label:     z.string().optional(),
    accept:    z.string().optional(),
    multiple:  z.boolean().optional(),
    maxSizeMb: z.number().optional(),
    hint:      z.string().optional(),
    bind:      z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type FileUploadNodeT = z.infer<typeof FileUploadNode>;

const ComboOption = z.object({ value: z.string().min(1), label: z.string().min(1) }).strict();
export const ComboboxNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Combobox"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    options:     z.array(ComboOption).min(1),
    optionsFrom: OptionsFrom.optional(),
    placeholder: z.string().optional(),
    filterable:  z.boolean().optional(),
    clearable:   z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ComboboxNodeT = z.infer<typeof ComboboxNode>;

export const TimePickerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("TimePicker"),
  props: z.object({
    ...baseField,
    min:  z.string().optional(),
    max:  z.string().optional(),
    step: z.number().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TimePickerNodeT = z.infer<typeof TimePickerNode>;

export const ColorPickerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("ColorPicker"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().optional(),
    disabled: z.boolean().optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ColorPickerNodeT = z.infer<typeof ColorPickerNode>;

export const InputOTPNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("InputOTP"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().optional(),
    length:   z.number().int().positive().optional(),
    disabled: z.boolean().optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type InputOTPNodeT = z.infer<typeof InputOTPNode>;

export const RatingNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Rating"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().optional(),
    max:      z.number().int().positive().optional(),
    disabled: z.boolean().optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type RatingNodeT = z.infer<typeof RatingNode>;

export const MaskedInputNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("MaskedInput"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    mask:        z.string().min(1),
    placeholder: z.string().optional(),
    disabled:    z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type MaskedInputNodeT = z.infer<typeof MaskedInputNode>;

// Editable string→value map for a jsonb / config column. Submits its value as a
// JSON string (via a hidden input); the runtime data engine parses it back.
export const KeyValueInputNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("KeyValueInput"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    description: z.string().optional(),
    valueType:   z.enum(["text", "number", "boolean"]).optional(),
    disabled:    z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type KeyValueInputNodeT = z.infer<typeof KeyValueInputNode>;
