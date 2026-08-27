"use client";

import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVisualEditorStore } from "@/stores/visual-editor";

const COLOR_SWATCHES = [
  { label: "White", tw: "white", hex: "#ffffff" },
  { label: "Gray Light", tw: "gray-100", hex: "#f3f4f6" },
  { label: "Gray Dark", tw: "gray-800", hex: "#1f2937" },
  { label: "Black", tw: "black", hex: "#000000" },
  { label: "Blue", tw: "blue-500", hex: "#3b82f6" },
  { label: "Green", tw: "green-500", hex: "#22c55e" },
  { label: "Red", tw: "red-500", hex: "#ef4444" },
  { label: "Yellow", tw: "yellow-500", hex: "#eab308" },
  { label: "Purple", tw: "purple-500", hex: "#a855f7" },
  { label: "Pink", tw: "pink-500", hex: "#ec4899" },
  { label: "Indigo", tw: "indigo-500", hex: "#6366f1" },
  { label: "Teal", tw: "teal-500", hex: "#14b8a6" },
] as const;

const SPACING_OPTIONS = [
  { label: "None", tw: "p-0" },
  { label: "Small", tw: "p-2" },
  { label: "Medium", tw: "p-4" },
  { label: "Large", tw: "p-8" },
] as const;

const FONT_SIZE_OPTIONS = [
  { label: "Small", tw: "text-sm" },
  { label: "Base", tw: "text-base" },
  { label: "Large", tw: "text-lg" },
  { label: "XL", tw: "text-xl" },
  { label: "2XL", tw: "text-2xl" },
] as const;

const BORDER_RADIUS_OPTIONS = [
  { label: "None", tw: "rounded-none" },
  { label: "Small", tw: "rounded" },
  { label: "Large", tw: "rounded-lg" },
  { label: "Full", tw: "rounded-full" },
] as const;

type Tab = "bg" | "text" | "spacing" | "font" | "border";

const TABS: { key: Tab; label: string }[] = [
  { key: "bg", label: "Background" },
  { key: "text", label: "Text Color" },
  { key: "spacing", label: "Spacing" },
  { key: "font", label: "Font Size" },
  { key: "border", label: "Border" },
];

interface QuickStylePopoverProps {
  onBack: () => void;
  onStyleChange: (
    action: "add" | "remove" | "replace",
    cls: string,
    replaceCls?: string,
  ) => void;
}

export function QuickStylePopover({ onBack, onStyleChange }: QuickStylePopoverProps) {
  const quickStyleTarget = useVisualEditorStore((s) => s.quickStyleTarget);
  const setQuickStyleTarget = useVisualEditorStore((s) => s.setQuickStyleTarget);
  const selectedElement = useVisualEditorStore((s) => s.selectedElement);
  const [activeTab, setActiveTab] = useState<Tab>(quickStyleTarget ?? "bg");

  const currentClasses = selectedElement?.className?.split(/\s+/) ?? [];

  function findCurrentClass(prefix: string): string | undefined {
    return currentClasses.find((c) => c.startsWith(prefix));
  }

  function handleColorClick(type: "bg" | "text", twColor: string) {
    const prefix = type === "bg" ? "bg-" : "text-";
    const newClass = `${prefix}${twColor}`;
    const existing = findCurrentClass(prefix);
    if (existing) {
      onStyleChange("replace", existing, newClass);
    } else {
      onStyleChange("add", newClass);
    }
  }

  function handleSpacingClick(twClass: string) {
    const existing = findCurrentClass("p-");
    if (existing) {
      onStyleChange("replace", existing, twClass);
    } else {
      onStyleChange("add", twClass);
    }
  }

  function handleFontSizeClick(twClass: string) {
    const existing = findCurrentClass("text-");
    // Be careful not to match text-color classes — font sizes start with text-sm, text-base, etc.
    const fontExisting = currentClasses.find(
      (c) =>
        c === "text-xs" ||
        c === "text-sm" ||
        c === "text-base" ||
        c === "text-lg" ||
        c === "text-xl" ||
        c === "text-2xl" ||
        c === "text-3xl" ||
        c === "text-4xl",
    );
    if (fontExisting) {
      onStyleChange("replace", fontExisting, twClass);
    } else {
      onStyleChange("add", twClass);
    }
  }

  function handleBorderToggle(hasBorder: boolean) {
    if (hasBorder) {
      const existing = findCurrentClass("border-0");
      if (existing) {
        onStyleChange("replace", "border-0", "border");
      } else if (!currentClasses.includes("border")) {
        onStyleChange("add", "border");
      }
    } else {
      if (currentClasses.includes("border")) {
        onStyleChange("replace", "border", "border-0");
      }
    }
  }

  function handleBorderRadiusClick(twClass: string) {
    const existing = currentClasses.find(
      (c) =>
        c === "rounded-none" ||
        c === "rounded" ||
        c === "rounded-lg" ||
        c === "rounded-full" ||
        c === "rounded-md" ||
        c === "rounded-xl",
    );
    if (existing) {
      onStyleChange("replace", existing, twClass);
    } else {
      onStyleChange("add", twClass);
    }
  }

  return (
    <div className="rounded-lg border bg-popover shadow-lg w-[240px]">
      {/* Header */}
      <div className="flex items-center gap-1 border-b px-2 py-1.5">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={onBack}
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="text-xs font-medium">Quick Style</span>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 border-b px-1.5 py-1 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted"
            }`}
            onClick={() => {
              setActiveTab(tab.key);
              setQuickStyleTarget(tab.key);
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-2">
        {(activeTab === "bg" || activeTab === "text") && (
          <div className="grid grid-cols-6 gap-1.5">
            {COLOR_SWATCHES.map((swatch) => {
              const prefix = activeTab === "bg" ? "bg-" : "text-";
              const isActive = currentClasses.includes(`${prefix}${swatch.tw}`);
              return (
                <button
                  key={swatch.tw}
                  className={`h-7 w-7 rounded-md border-2 transition-all hover:scale-110 ${
                    isActive ? "border-primary ring-1 ring-primary" : "border-transparent"
                  }`}
                  style={{ backgroundColor: swatch.hex }}
                  title={swatch.label}
                  onClick={() => handleColorClick(activeTab, swatch.tw)}
                />
              );
            })}
          </div>
        )}

        {activeTab === "spacing" && (
          <div className="flex flex-wrap gap-1">
            {SPACING_OPTIONS.map((opt) => {
              const isActive = currentClasses.includes(opt.tw);
              return (
                <button
                  key={opt.tw}
                  className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                    isActive
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                  onClick={() => handleSpacingClick(opt.tw)}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        )}

        {activeTab === "font" && (
          <div className="flex flex-wrap gap-1">
            {FONT_SIZE_OPTIONS.map((opt) => {
              const isActive = currentClasses.includes(opt.tw);
              return (
                <button
                  key={opt.tw}
                  className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                    isActive
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                  onClick={() => handleFontSizeClick(opt.tw)}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        )}

        {activeTab === "border" && (
          <div className="space-y-2">
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">Border</p>
              <div className="flex gap-1">
                <button
                  className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                    currentClasses.includes("border")
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                  onClick={() => handleBorderToggle(true)}
                >
                  On
                </button>
                <button
                  className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                    !currentClasses.includes("border")
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                  onClick={() => handleBorderToggle(false)}
                >
                  Off
                </button>
              </div>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">Rounded</p>
              <div className="flex flex-wrap gap-1">
                {BORDER_RADIUS_OPTIONS.map((opt) => {
                  const isActive = currentClasses.includes(opt.tw);
                  return (
                    <button
                      key={opt.tw}
                      className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                        isActive
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border hover:bg-muted"
                      }`}
                      onClick={() => handleBorderRadiusClick(opt.tw)}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
