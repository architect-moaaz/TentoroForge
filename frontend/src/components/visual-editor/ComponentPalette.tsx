"use client";

import { useState, useEffect, useCallback } from "react";
import { Search, Plus, Sparkles, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAddSection } from "@/hooks/useAddSection";
import { useVisualEditorStore } from "@/stores/visual-editor";

interface SectionTemplate {
  id: string;
  name: string;
  category: string;
  description: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  all: "All",
  hero: "Hero",
  features: "Features",
  pricing: "Pricing",
  testimonials: "Testimonials",
  cta: "CTA",
  footer: "Footer",
  stats: "Stats",
  faq: "FAQ",
  team: "Team",
  contact: "Contact",
  content: "Content",
  gallery: "Gallery",
};

interface ComponentPaletteProps {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ComponentPalette({ projectId, open, onOpenChange }: ComponentPaletteProps) {
  const [templates, setTemplates] = useState<SectionTemplate[]>([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [customPrompt, setCustomPrompt] = useState("");
  const currentRoute = useVisualEditorStore((s) => s.currentRoute);
  const { addSection, isGenerating } = useAddSection(projectId);

  // Fetch templates when opened
  useEffect(() => {
    if (!open) return;
    api
      .get<SectionTemplate[]>(`/api/projects/${projectId}/visual-edit/section-templates`)
      .then(setTemplates)
      .catch(() => {});
  }, [projectId, open]);

  const filtered = templates.filter((t) => {
    if (category !== "all" && t.category !== category) return false;
    if (search && !t.name.toLowerCase().includes(search.toLowerCase()) && !t.description.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const categories = ["all", ...new Set(templates.map((t) => t.category))];

  const handleAddTemplate = useCallback(
    async (templateId: string) => {
      await addSection({
        route: currentRoute || "/",
        template_id: templateId,
        insert_position: "end",
      });
      onOpenChange(false);
    },
    [addSection, currentRoute, onOpenChange],
  );

  const handleCustomGenerate = useCallback(async () => {
    if (!customPrompt.trim()) return;
    await addSection({
      route: currentRoute || "/",
      custom_prompt: customPrompt.trim(),
      insert_position: "end",
    });
    setCustomPrompt("");
    onOpenChange(false);
  }, [addSection, currentRoute, customPrompt, onOpenChange]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-[340px] p-0 flex flex-col">
        <SheetHeader className="px-4 pt-4 pb-2">
          <SheetTitle className="text-sm">Add Section</SheetTitle>
        </SheetHeader>

        {/* Search */}
        <div className="px-4 pb-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              className="h-8 pl-8 text-sm"
              placeholder="Search templates..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Category tabs */}
        <div className="px-4 pb-2 flex gap-1 flex-wrap">
          {categories.map((cat) => (
            <button
              key={cat}
              className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
                category === cat
                  ? "bg-primary text-primary-foreground border-primary"
                  : "hover:bg-muted border-transparent"
              }`}
              onClick={() => setCategory(cat)}
            >
              {CATEGORY_LABELS[cat] || cat}
            </button>
          ))}
        </div>

        <Separator />

        {/* Template list */}
        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
          {filtered.map((template) => (
            <div
              key={template.id}
              className="rounded-lg border p-3 hover:border-primary/50 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{template.name}</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">
                    {template.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => handleAddTemplate(template.id)}
                  disabled={isGenerating}
                >
                  {isGenerating ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <>
                      <Plus className="h-3 w-3 mr-0.5" />
                      Add
                    </>
                  )}
                </Button>
              </div>
            </div>
          ))}
          {filtered.length === 0 && templates.length > 0 && (
            <p className="text-xs text-muted-foreground text-center py-4">No templates match</p>
          )}
          {templates.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-4">Loading templates...</p>
          )}
        </div>

        <Separator />

        {/* Custom prompt */}
        <div className="p-4 space-y-2">
          <p className="text-xs font-medium">Custom Section</p>
          <Textarea
            className="text-sm resize-none"
            rows={3}
            placeholder="Describe a custom section..."
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
          />
          <Button
            className="w-full gap-1.5"
            size="sm"
            onClick={handleCustomGenerate}
            disabled={!customPrompt.trim() || isGenerating}
          >
            {isGenerating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Generate Custom Section
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
