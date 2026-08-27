"use client";

import { useCallback } from "react";
import type { NodeRendererProps } from "../types";
import { NodeWrapper } from "../NodeWrapper";
import { useRendererContext } from "../RendererContext";
import { resolveBinding } from "../bindings";
import { buildClasses } from "../tokens";

function InputLabel({ node, children }: { node: NodeRendererProps["node"]; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      {Boolean(node.label) && <label className="text-sm font-medium text-gray-900">{String(node.label)}</label>}
      {children}
      {Boolean(node.hint) && <p className="text-xs text-gray-500">{String(node.hint)}</p>}
      {Boolean(node.error) && <p className="text-xs text-red-500">{String(node.error)}</p>}
    </div>
  );
}

export function TextInputRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  const onChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (bindPath) ctx.setState(bindPath, e.target.value);
    },
    [ctx, bindPath],
  );

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <input
          type={(node.type as string) ?? "text"}
          value={String(value)}
          onChange={onChange}
          placeholder={(node.placeholder as string) ?? ""}
          disabled={Boolean(node.disabled)}
          className={buildClasses(
            "w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
            Boolean(node.disabled) && "bg-gray-50 text-gray-500",
          )}
        />
      </InputLabel>
    </NodeWrapper>
  );
}

export function TextAreaRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  const onChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      if (bindPath) ctx.setState(bindPath, e.target.value);
    },
    [ctx, bindPath],
  );

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <textarea
          value={String(value)}
          onChange={onChange}
          rows={(node.rows as number) ?? 3}
          placeholder={(node.placeholder as string) ?? ""}
          disabled={Boolean(node.disabled)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </InputLabel>
    </NodeWrapper>
  );
}

export function SelectRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";
  const options = (node.options as Array<{ label: string; value: string }>) ?? [];

  const onChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      if (bindPath) ctx.setState(bindPath, e.target.value);
    },
    [ctx, bindPath],
  );

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <select
          value={String(value)}
          onChange={onChange}
          disabled={Boolean(node.disabled)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {Boolean(node.placeholder) && <option value="">{String(node.placeholder)}</option>}
          {options.map((opt, i) => (
            <option key={i} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </InputLabel>
    </NodeWrapper>
  );
}

export function CheckboxRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const checked = Boolean(resolveBinding(node.bind, ctx));
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  return (
    <NodeWrapper node={node} path={path}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => bindPath && ctx.setState(bindPath, e.target.checked)}
          disabled={Boolean(node.disabled)}
          className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        <div>
          {Boolean(node.label) && <span className="text-sm font-medium text-gray-900">{String(node.label)}</span>}
          {Boolean(node.description) && <p className="text-xs text-gray-500">{String(node.description)}</p>}
        </div>
      </div>
    </NodeWrapper>
  );
}

export function ToggleRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const checked = Boolean(resolveBinding(node.bind, ctx));
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  return (
    <NodeWrapper node={node} path={path}>
      <div className="flex items-center justify-between gap-2">
        <div>
          {Boolean(node.label) && <span className="text-sm font-medium text-gray-900">{String(node.label)}</span>}
          {Boolean(node.description) && <p className="text-xs text-gray-500">{String(node.description)}</p>}
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          onClick={() => bindPath && ctx.setState(bindPath, !checked)}
          className={buildClasses(
            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
            checked ? "bg-blue-600" : "bg-gray-200",
          )}
        >
          <span className={buildClasses("pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform", checked ? "translate-x-5" : "translate-x-0")} />
        </button>
      </div>
    </NodeWrapper>
  );
}

export function RadioGroupRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";
  const options = (node.options as Array<{ label: string; value: string }>) ?? [];
  const direction = (node.direction as string) ?? "col";

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <div className={buildClasses("flex gap-3", direction === "row" ? "flex-row" : "flex-col")}>
          {options.map((opt, i) => (
            <label key={i} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={value === opt.value}
                onChange={() => bindPath && ctx.setState(bindPath, opt.value)}
                className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm">{opt.label}</span>
            </label>
          ))}
        </div>
      </InputLabel>
    </NodeWrapper>
  );
}

export function DatePickerRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <input
          type={node.includeTime ? "datetime-local" : "date"}
          value={String(value)}
          onChange={(e) => bindPath && ctx.setState(bindPath, e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </InputLabel>
    </NodeWrapper>
  );
}

export function FilePickerRenderer({ node, path }: NodeRendererProps) {
  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <div className="flex items-center justify-center w-full h-20 border-2 border-dashed border-gray-300 rounded-md text-sm text-gray-500 hover:border-gray-400 cursor-pointer">
          Click to upload{node.accept ? ` (${String(node.accept)})` : ""}
        </div>
      </InputLabel>
    </NodeWrapper>
  );
}

export function SliderRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = Number(resolveBinding(node.bind, ctx) ?? node.min ?? 0);
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={(node.min as number) ?? 0}
            max={(node.max as number) ?? 100}
            step={(node.step as number) ?? 1}
            value={value}
            onChange={(e) => bindPath && ctx.setState(bindPath, Number(e.target.value))}
            className="flex-1"
          />
          {Boolean(node.showValue) && <span className="text-sm text-gray-600 w-10 text-right">{value}</span>}
        </div>
      </InputLabel>
    </NodeWrapper>
  );
}

export function ColorPickerRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const value = resolveBinding(node.bind, ctx) ?? "#000000";
  const bindPath = typeof node.bind === "string" && node.bind.startsWith("state:") ? node.bind.slice(6) : "";

  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <input
          type="color"
          value={String(value)}
          onChange={(e) => bindPath && ctx.setState(bindPath, e.target.value)}
          className="h-10 w-full rounded border border-gray-300 cursor-pointer"
        />
      </InputLabel>
    </NodeWrapper>
  );
}

export function RichTextEditorRenderer({ node, path }: NodeRendererProps) {
  return (
    <NodeWrapper node={node} path={path}>
      <InputLabel node={node}>
        <div className="w-full min-h-[120px] border border-gray-300 rounded-md p-3 text-sm text-gray-400">
          Rich text editor placeholder
        </div>
      </InputLabel>
    </NodeWrapper>
  );
}
