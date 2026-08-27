/**
 * Input node emitters: TextInput, TextArea, Select, Checkbox, Toggle,
 * RadioGroup, DatePicker, FilePicker, RichTextEditor, Slider, ColorPicker
 */

import type {
  TextInputNode, TextAreaNode, SelectNode, CheckboxNode, ToggleNode,
  RadioGroupNode, DatePickerNode, FilePickerNode, RichTextEditorNode,
  SliderNode, ColorPickerNode, SelectOption,
} from "@tentoroforge/ir";
import { EmitContext } from "../context.js";
import { emitStateBinding } from "../bindings.js";

function kebabToPascal(s: string): string {
  return s.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
}

// ---------------------------------------------------------------------------
// Wrappers
// ---------------------------------------------------------------------------

function wrapWithLabel(inner: string, node: { label?: string; hint?: string; error?: string }): string {
  if (!node.label) return inner;
  let result = `<div className="space-y-2">\n<label className="text-sm font-medium">${node.label}</label>\n${inner}`;
  if (node.hint) {
    result += `\n<p className="text-xs text-muted-foreground">${node.hint}</p>`;
  }
  if (node.error) {
    result += `\n<p className="text-xs text-destructive">{${node.error}}</p>`;
  }
  result += "\n</div>";
  return result;
}

// ---------------------------------------------------------------------------
// TextInput
// ---------------------------------------------------------------------------

export function emitTextInput(node: TextInputNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/input", "Input");
  const { getter, setter, stateKey } = emitStateBinding(node.bind, ctx);

  // Debounce support
  if (node.debounce) {
    ctx.ensureImport("react", "useState", "useEffect");
    const debouncedVar = `debounced${stateKey.charAt(0).toUpperCase()}${stateKey.slice(1)}`;
    ctx.addState(debouncedVar, "string", `${getter}`);
    ctx.addEffect(
      `useEffect(() => {\n  const timer = setTimeout(() => set${debouncedVar.charAt(0).toUpperCase()}${debouncedVar.slice(1)}(${getter}), ${node.debounce});\n  return () => clearTimeout(timer);\n}, [${getter}]);`,
    );
  }

  const props: string[] = [
    `type="${node.type || "text"}"`,
    `placeholder="${node.placeholder || ""}"`,
    `value={${getter}}`,
    `onChange={(e) => ${setter}(e.target.value)}`,
  ];
  if (node.disabled) props.push(`disabled`);
  if (node.maxLength) props.push(`maxLength={${node.maxLength}}`);

  let inner: string;

  if (node.icon) {
    const iconName = kebabToPascal(node.icon);
    ctx.ensureImport("lucide-react", iconName);
    inner = `<div className="relative">
<${iconName} className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
<Input className="pl-9" ${props.join(" ")} />
</div>`;
  } else {
    inner = `<Input ${props.join(" ")} />`;
  }

  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// TextArea
// ---------------------------------------------------------------------------

export function emitTextArea(node: TextAreaNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/textarea", "Textarea");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const props: string[] = [
    `placeholder="${node.placeholder || ""}"`,
    `value={${getter}}`,
    `onChange={(e) => ${setter}(e.target.value)}`,
    `rows={${node.rows || 3}}`,
  ];

  const inner = `<Textarea ${props.join(" ")} />`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// Select
// ---------------------------------------------------------------------------

export function emitSelect(node: SelectNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/select", "Select", "SelectTrigger", "SelectValue", "SelectContent", "SelectItem");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  if (Array.isArray(node.options)) {
    // Static options
    const optionEls = (node.options as SelectOption[])
      .map((opt) => `<SelectItem value="${opt.value}">${opt.label}</SelectItem>`)
      .join("\n");

    const inner = `<Select value={${getter}} onValueChange={${setter}}>
<SelectTrigger>
<SelectValue placeholder="${node.placeholder || "Select..."}" />
</SelectTrigger>
<SelectContent>
${optionEls}
</SelectContent>
</Select>`;
    return wrapWithLabel(inner, node);
  }

  // Dynamic options from data source
  const dynOpts = node.options as { source: string; value: string; label: string };
  const dataVar = `${dynOpts.source}Data`;
  const inner = `<Select value={${getter}} onValueChange={${setter}}>
<SelectTrigger>
<SelectValue placeholder="${node.placeholder || "Select..."}" />
</SelectTrigger>
<SelectContent>
{${dataVar}?.items?.map((opt: any) => (
<SelectItem key={opt.${dynOpts.value}} value={opt.${dynOpts.value}}>{opt.${dynOpts.label}}</SelectItem>
))}
</SelectContent>
</Select>`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// Checkbox
// ---------------------------------------------------------------------------

export function emitCheckbox(node: CheckboxNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/checkbox", "Checkbox");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  return `<div className="flex items-start gap-2">
<Checkbox checked={${getter}} onCheckedChange={${setter}} />
<div>
${node.label ? `<label className="text-sm font-medium">${node.label}</label>` : ""}
${node.description ? `<p className="text-xs text-muted-foreground">${node.description}</p>` : ""}
</div>
</div>`;
}

// ---------------------------------------------------------------------------
// Toggle
// ---------------------------------------------------------------------------

export function emitToggle(node: ToggleNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/switch", "Switch");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  return `<div className="flex items-center justify-between">
<div>
${node.label ? `<label className="text-sm font-medium">${node.label}</label>` : ""}
${node.description ? `<p className="text-xs text-muted-foreground">${node.description}</p>` : ""}
</div>
<Switch checked={${getter}} onCheckedChange={${setter}} />
</div>`;
}

// ---------------------------------------------------------------------------
// RadioGroup
// ---------------------------------------------------------------------------

export function emitRadioGroup(node: RadioGroupNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/radio-group", "RadioGroup", "RadioGroupItem");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const direction = node.direction === "row" ? "flex-row" : "flex-col";
  const optionEls = node.options
    .map(
      (opt) =>
        `<div className="flex items-center gap-2">
<RadioGroupItem value="${opt.value}" id="${opt.value}" />
<label htmlFor="${opt.value}" className="text-sm">${opt.label}</label>
</div>`,
    )
    .join("\n");

  const inner = `<RadioGroup value={${getter}} onValueChange={${setter}} className="flex ${direction} gap-2">
${optionEls}
</RadioGroup>`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// DatePicker (simplified)
// ---------------------------------------------------------------------------

export function emitDatePicker(node: DatePickerNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/input", "Input");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const inner = `<Input type="${node.includeTime ? "datetime-local" : "date"}" value={${getter}} onChange={(e) => ${setter}(e.target.value)} />`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// FilePicker (simplified)
// ---------------------------------------------------------------------------

export function emitFilePicker(node: FilePickerNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/input", "Input");
  const { setter } = emitStateBinding(node.bind, ctx);

  const props: string[] = [
    `type="file"`,
    node.accept ? `accept="${node.accept}"` : "",
    node.multiple ? "multiple" : "",
    `onChange={(e) => ${setter}(e.target.files)}`,
  ].filter(Boolean);

  const inner = `<Input ${props.join(" ")} />`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// RichTextEditor (simplified — renders as TextArea)
// ---------------------------------------------------------------------------

export function emitRichTextEditor(node: RichTextEditorNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/textarea", "Textarea");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const inner = `<Textarea value={${getter}} onChange={(e) => ${setter}(e.target.value)} rows={8} className="min-h-[200px]" />`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// Slider (simplified)
// ---------------------------------------------------------------------------

export function emitSlider(node: SliderNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/slider", "Slider");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const inner = `<Slider min={${node.min}} max={${node.max}} step={${node.step || 1}} value={[${getter}]} onValueChange={(v) => ${setter}(v[0])} />`;
  return wrapWithLabel(inner, node);
}

// ---------------------------------------------------------------------------
// ColorPicker (simplified — renders as text input)
// ---------------------------------------------------------------------------

export function emitColorPicker(node: ColorPickerNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/input", "Input");
  const { getter, setter } = emitStateBinding(node.bind, ctx);

  const inner = `<Input type="color" value={${getter}} onChange={(e) => ${setter}(e.target.value)} />`;
  return wrapWithLabel(inner, node);
}
