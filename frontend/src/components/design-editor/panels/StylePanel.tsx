"use client";

/**
 * StylePanel — React-driven style editor for the selected GrapeJS element.
 *
 * Sections:
 *   Background  — image URL, color, size, position, repeat
 *   Typography  — font size, weight, color, alignment
 *   Spacing     — padding, margin
 *   Size        — width, height
 */

import { useCallback, useEffect, useState } from "react";
import type { Editor, Component as GjsComponent } from "grapesjs";

interface StylePanelProps {
  editor: Editor | null;
}

// ---------------------------------------------------------------------------
// Hook: track selected element + its styles
// ---------------------------------------------------------------------------

function useSelectedStyles(editor: Editor | null) {
  const [selected, setSelected] = useState<GjsComponent | null>(null);
  const [styles, setStyles] = useState<Record<string, string>>({});

  const refresh = useCallback((comp: GjsComponent | null) => {
    setSelected(comp);
    setStyles(comp ? (comp.getStyle() as Record<string, string>) : {});
  }, []);

  useEffect(() => {
    if (!editor) return;
    const onSelect = (c: GjsComponent) => refresh(c);
    const onDeselect = () => refresh(null);
    const onChange = () => refresh(editor.getSelected() ?? null);
    editor.on("component:selected", onSelect);
    editor.on("component:deselected", onDeselect);
    editor.on("component:styleUpdate", onChange);
    return () => {
      editor.off("component:selected", onSelect);
      editor.off("component:deselected", onDeselect);
      editor.off("component:styleUpdate", onChange);
    };
  }, [editor, refresh]);

  const setStyle = useCallback(
    (prop: string, value: string) => {
      if (!selected) return;
      const updated = { ...styles };
      if (value) updated[prop] = value;
      else delete updated[prop];
      selected.setStyle(updated);
      setStyles({ ...updated });
    },
    [selected, styles],
  );

  return { selected, styles, setStyle };
}

// ---------------------------------------------------------------------------
// Field helpers
// ---------------------------------------------------------------------------

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-muted-foreground w-24 shrink-0">{label}</span>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function Inp({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full h-7 rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
    />
  );
}

function Sel({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full h-7 rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="px-3 py-1.5 bg-muted/40 border-b border-t">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background image preview helper
// ---------------------------------------------------------------------------

function extractBgUrl(bgImage: string): string {
  const m = bgImage.match(/url\(["']?([^"')]+)["']?\)/);
  return m ? m[1] : "";
}

function buildBgUrl(url: string): string {
  if (!url) return "";
  return `url('${url}')`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function StylePanel({ editor }: StylePanelProps) {
  const { selected, styles, setStyle } = useSelectedStyles(editor);

  const g = (prop: string) => styles[prop] || "";

  const bgUrl = extractBgUrl(g("background-image"));

  if (!selected) {
    return (
      <div className="p-4 text-xs text-muted-foreground text-center">
        Select an element on the canvas to edit its styles.
      </div>
    );
  }

  const tag = selected.get("tagName") || "div";
  const cls = selected.getClasses().slice(0, 2).join(" ");

  return (
    <div className="flex flex-col text-xs overflow-y-auto">
      {/* Element badge */}
      <div className="px-3 py-2 border-b text-[11px] text-muted-foreground">
        <span className="font-mono bg-muted px-1 rounded">{tag}</span>
        {cls && <span className="ml-1 text-muted-foreground/60 truncate">.{cls}</span>}
      </div>

      {/* ── Background ────────────────────────────────────────────────── */}
      <SectionHeader title="Background" />
      <div className="px-3 py-2 space-y-2">
        <Row label="Color">
          <div className="flex gap-1.5">
            <input
              type="color"
              value={g("background-color") || "#ffffff"}
              onChange={(e) => setStyle("background-color", e.target.value)}
              className="h-7 w-8 rounded border border-input cursor-pointer p-0.5"
            />
            <Inp
              value={g("background-color")}
              onChange={(v) => setStyle("background-color", v)}
              placeholder="transparent"
            />
          </div>
        </Row>

        <Row label="Image URL">
          <Inp
            value={bgUrl}
            onChange={(v) => setStyle("background-image", buildBgUrl(v))}
            placeholder="https://… or /image.jpg"
          />
        </Row>

        {/* Image preview */}
        {bgUrl && (
          <div
            className="w-full h-16 rounded-md border overflow-hidden bg-muted"
            style={{ backgroundImage: `url('${bgUrl}')`, backgroundSize: "cover", backgroundPosition: "center" }}
          />
        )}

        <Row label="Size">
          <Sel
            value={g("background-size")}
            onChange={(v) => setStyle("background-size", v)}
            options={[
              { value: "", label: "Default" },
              { value: "cover", label: "Cover (fill, crop if needed)" },
              { value: "contain", label: "Contain (fit, show all)" },
              { value: "auto", label: "Auto (original size)" },
              { value: "100% 100%", label: "Stretch (100% × 100%)" },
              { value: "50%", label: "Half size (50%)" },
            ]}
          />
        </Row>

        <Row label="Position">
          <Sel
            value={g("background-position")}
            onChange={(v) => setStyle("background-position", v)}
            options={[
              { value: "", label: "Default" },
              { value: "center center", label: "Center" },
              { value: "top center", label: "Top center" },
              { value: "bottom center", label: "Bottom center" },
              { value: "left center", label: "Left center" },
              { value: "right center", label: "Right center" },
              { value: "top left", label: "Top left" },
              { value: "top right", label: "Top right" },
              { value: "bottom left", label: "Bottom left" },
              { value: "bottom right", label: "Bottom right" },
            ]}
          />
        </Row>

        <Row label="Repeat">
          <Sel
            value={g("background-repeat")}
            onChange={(v) => setStyle("background-repeat", v)}
            options={[
              { value: "", label: "Default" },
              { value: "no-repeat", label: "No repeat" },
              { value: "repeat", label: "Repeat (tile)" },
              { value: "repeat-x", label: "Repeat horizontal" },
              { value: "repeat-y", label: "Repeat vertical" },
            ]}
          />
        </Row>

        <Row label="Attachment">
          <Sel
            value={g("background-attachment")}
            onChange={(v) => setStyle("background-attachment", v)}
            options={[
              { value: "", label: "Default" },
              { value: "scroll", label: "Scroll with page" },
              { value: "fixed", label: "Fixed (parallax)" },
              { value: "local", label: "Local (scroll with element)" },
            ]}
          />
        </Row>
      </div>

      {/* ── Typography ────────────────────────────────────────────────── */}
      <SectionHeader title="Typography" />
      <div className="px-3 py-2 space-y-2">
        <Row label="Font size">
          <Inp value={g("font-size")} onChange={(v) => setStyle("font-size", v)} placeholder="16px / 1rem" />
        </Row>
        <Row label="Font weight">
          <Sel
            value={g("font-weight")}
            onChange={(v) => setStyle("font-weight", v)}
            options={[
              { value: "", label: "Default" },
              { value: "300", label: "Light (300)" },
              { value: "400", label: "Regular (400)" },
              { value: "500", label: "Medium (500)" },
              { value: "600", label: "SemiBold (600)" },
              { value: "700", label: "Bold (700)" },
            ]}
          />
        </Row>
        <Row label="Color">
          <div className="flex gap-1.5">
            <input
              type="color"
              value={g("color") || "#000000"}
              onChange={(e) => setStyle("color", e.target.value)}
              className="h-7 w-8 rounded border border-input cursor-pointer p-0.5"
            />
            <Inp value={g("color")} onChange={(v) => setStyle("color", v)} placeholder="#000 / rgb(…)" />
          </div>
        </Row>
        <Row label="Align">
          <Sel
            value={g("text-align")}
            onChange={(v) => setStyle("text-align", v)}
            options={[
              { value: "", label: "Default" },
              { value: "left", label: "Left" },
              { value: "center", label: "Center" },
              { value: "right", label: "Right" },
              { value: "justify", label: "Justify" },
            ]}
          />
        </Row>
        <Row label="Line height">
          <Inp value={g("line-height")} onChange={(v) => setStyle("line-height", v)} placeholder="1.5" />
        </Row>
      </div>

      {/* ── Spacing ───────────────────────────────────────────────────── */}
      <SectionHeader title="Spacing" />
      <div className="px-3 py-2 space-y-2">
        <Row label="Padding">
          <Inp value={g("padding")} onChange={(v) => setStyle("padding", v)} placeholder="8px / 8px 16px" />
        </Row>
        <Row label="Margin">
          <Inp value={g("margin")} onChange={(v) => setStyle("margin", v)} placeholder="8px / 0 auto" />
        </Row>
        <Row label="Gap">
          <Inp value={g("gap")} onChange={(v) => setStyle("gap", v)} placeholder="8px" />
        </Row>
      </div>

      {/* ── Size ──────────────────────────────────────────────────────── */}
      <SectionHeader title="Size" />
      <div className="px-3 py-2 space-y-2">
        <Row label="Width">
          <Inp value={g("width")} onChange={(v) => setStyle("width", v)} placeholder="100% / 400px" />
        </Row>
        <Row label="Height">
          <Inp value={g("height")} onChange={(v) => setStyle("height", v)} placeholder="auto / 200px" />
        </Row>
        <Row label="Min height">
          <Inp value={g("min-height")} onChange={(v) => setStyle("min-height", v)} placeholder="100px" />
        </Row>
        <Row label="Border radius">
          <Inp value={g("border-radius")} onChange={(v) => setStyle("border-radius", v)} placeholder="8px / 50%" />
        </Row>
        <Row label="Opacity">
          <Inp value={g("opacity")} onChange={(v) => setStyle("opacity", v)} placeholder="1 (0–1)" />
        </Row>
      </div>

      {/* ── Border ────────────────────────────────────────────────────── */}
      <SectionHeader title="Border" />
      <div className="px-3 py-2 space-y-2">
        <Row label="Border">
          <Inp value={g("border")} onChange={(v) => setStyle("border", v)} placeholder="1px solid #ccc" />
        </Row>
        <Row label="Box shadow">
          <Inp value={g("box-shadow")} onChange={(v) => setStyle("box-shadow", v)} placeholder="0 2px 8px rgba(0,0,0,0.1)" />
        </Row>
      </div>

      {/* Spacer */}
      <div className="h-4" />
    </div>
  );
}
