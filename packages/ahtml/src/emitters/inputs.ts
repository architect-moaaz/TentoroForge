/**
 * Input node → Annotated HTML emitters: TextInput, TextArea, Select, Checkbox,
 * Toggle, RadioGroup, DatePicker, FilePicker, RichTextEditor, Slider, ColorPicker
 */

import type {
  TextInputNode, TextAreaNode, SelectNode, CheckboxNode, ToggleNode,
  RadioGroupNode, DatePickerNode, FilePickerNode, RichTextEditorNode,
  SliderNode, ColorPickerNode, SelectOption,
} from "@tentoroforge/ir";
import { indent } from "../ir-to-html.js";

// ---------------------------------------------------------------------------
// Label wrapper
// ---------------------------------------------------------------------------

function wrapWithLabel(inner: string, node: { label?: string; hint?: string }, depth: number): string {
  if (!node.label) return inner;
  const pad = indent(depth);
  let result = `${pad}<div class="space-y-2">\n${indent(depth + 1)}<label class="text-sm font-medium">${node.label}</label>\n${inner}`;
  if (node.hint) {
    result += `\n${indent(depth + 1)}<p class="text-xs text-muted-foreground">${node.hint}</p>`;
  }
  result += `\n${pad}</div>`;
  return result;
}

// ---------------------------------------------------------------------------
// TextInput
// ---------------------------------------------------------------------------

export function emitTextInputHtml(node: TextInputNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const attrs: string[] = [
    `type="${node.type || "text"}"`,
    `class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"`,
    `placeholder="${node.placeholder || ""}"`,
    `data-bind="${node.bind}"`,
  ];
  if (node.disabled) attrs.push("disabled");
  if (node.maxLength) attrs.push(`maxlength="${node.maxLength}"`);
  if (node.required) attrs.push("required");

  const inner = `${pad}<input ${attrs.join(" ")} />`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// TextArea
// ---------------------------------------------------------------------------

export function emitTextAreaHtml(node: TextAreaNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const attrs: string[] = [
    `class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"`,
    `placeholder="${node.placeholder || ""}"`,
    `rows="${node.rows || 3}"`,
    `data-bind="${node.bind}"`,
  ];
  if (node.required) attrs.push("required");

  const inner = `${pad}<textarea ${attrs.join(" ")}></textarea>`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// Select
// ---------------------------------------------------------------------------

export function emitSelectHtml(node: SelectNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const attrs: string[] = [
    `class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"`,
    `data-bind="${node.bind}"`,
  ];
  if (node.required) attrs.push("required");

  let options = "";
  if (Array.isArray(node.options)) {
    options = (node.options as SelectOption[])
      .map((opt) => `${indent(depth + 2)}<option value="${opt.value}">${opt.label}</option>`)
      .join("\n");
  }

  const placeholder = node.placeholder || "Select...";
  const inner = `${pad}<select ${attrs.join(" ")}>
${indent(depth + 2)}<option value="">${placeholder}</option>
${options}
${pad}</select>`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// Checkbox
// ---------------------------------------------------------------------------

export function emitCheckboxHtml(node: CheckboxNode, depth: number): string {
  const pad = indent(depth);
  return `${pad}<div class="flex items-start gap-2">
${indent(depth + 1)}<input type="checkbox" class="mt-1" data-bind="${node.bind}" />
${indent(depth + 1)}<div>
${node.label ? `${indent(depth + 2)}<label class="text-sm font-medium">${node.label}</label>` : ""}
${node.description ? `${indent(depth + 2)}<p class="text-xs text-muted-foreground">${node.description}</p>` : ""}
${indent(depth + 1)}</div>
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Toggle
// ---------------------------------------------------------------------------

export function emitToggleHtml(node: ToggleNode, depth: number): string {
  const pad = indent(depth);
  return `${pad}<div class="flex items-center justify-between">
${indent(depth + 1)}<div>
${node.label ? `${indent(depth + 2)}<label class="text-sm font-medium">${node.label}</label>` : ""}
${node.description ? `${indent(depth + 2)}<p class="text-xs text-muted-foreground">${node.description}</p>` : ""}
${indent(depth + 1)}</div>
${indent(depth + 1)}<input type="checkbox" role="switch" class="toggle" data-bind="${node.bind}" />
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// RadioGroup
// ---------------------------------------------------------------------------

export function emitRadioGroupHtml(node: RadioGroupNode, depth: number): string {
  const direction = node.direction === "row" ? "flex-row" : "flex-col";
  const optionEls = node.options
    .map((opt) =>
      `${indent(depth + 2)}<div class="flex items-center gap-2">
${indent(depth + 3)}<input type="radio" name="${node.bind}" value="${opt.value}" data-bind="${node.bind}" />
${indent(depth + 3)}<label class="text-sm">${opt.label}</label>
${indent(depth + 2)}</div>`,
    )
    .join("\n");

  const pad = indent(depth + (node.label ? 1 : 0));
  const inner = `${pad}<div class="flex ${direction} gap-2" data-component="RadioGroup">
${optionEls}
${pad}</div>`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// DatePicker
// ---------------------------------------------------------------------------

export function emitDatePickerHtml(node: DatePickerNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const type = node.includeTime ? "datetime-local" : "date";
  const inner = `${pad}<input type="${type}" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="${node.bind}" />`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// FilePicker
// ---------------------------------------------------------------------------

export function emitFilePickerHtml(node: FilePickerNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const attrs: string[] = [
    `type="file"`,
    `class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"`,
    `data-bind="${node.bind}"`,
  ];
  if (node.accept) attrs.push(`accept="${node.accept}"`);
  if (node.multiple) attrs.push("multiple");

  const inner = `${pad}<input ${attrs.join(" ")} />`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// RichTextEditor (as textarea)
// ---------------------------------------------------------------------------

export function emitRichTextEditorHtml(node: RichTextEditorNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const inner = `${pad}<textarea class="flex min-h-[200px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="${node.bind}" rows="8"></textarea>`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// Slider
// ---------------------------------------------------------------------------

export function emitSliderHtml(node: SliderNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const inner = `${pad}<input type="range" min="${node.min}" max="${node.max}" step="${node.step || 1}" class="w-full" data-bind="${node.bind}" />`;
  return wrapWithLabel(inner, node, depth);
}

// ---------------------------------------------------------------------------
// ColorPicker
// ---------------------------------------------------------------------------

export function emitColorPickerHtml(node: ColorPickerNode, depth: number): string {
  const pad = indent(depth + (node.label ? 1 : 0));
  const inner = `${pad}<input type="color" class="h-10 w-10 rounded border" data-bind="${node.bind}" />`;
  return wrapWithLabel(inner, node, depth);
}
