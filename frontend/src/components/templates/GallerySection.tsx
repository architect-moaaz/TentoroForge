"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { TemplateCardData } from "@/lib/templateGallery";
import { GalleryCard } from "./GalleryCard";

const SORTS = [
  ["popular", "Most used"],
  ["rating", "Top rated"],
  ["newest", "Newest"],
] as const;

/** The Templates Gallery: every template Tentoro approved, from every organisation. */
export function GallerySection({
  search,
  onOpen,
  onOpenCreator,
}: {
  search: string;
  onOpen: (templateId: string) => void;
  onOpenCreator: (userId: string) => void;
}) {
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<(typeof SORTS)[number][0]>("popular");
  const { data, isLoading } = useQuery({
    queryKey: ["template-gallery", search, category, sort],
    queryFn: () => {
      const qs = new URLSearchParams({ sort });
      if (search.trim()) qs.set("search", search.trim());
      if (category) qs.set("category", category);
      return api.get<{ templates: TemplateCardData[]; categories: string[] }>(`/api/template-gallery?${qs}`);
    },
  });
  const templates = data?.templates ?? [];
  return (
    <section className="mb-10" aria-labelledby="gallery-heading">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="gallery-heading" className="flex items-center gap-1.5 text-base font-semibold text-foreground">
            <Sparkles className="h-4 w-4" /> Templates Gallery
          </h2>
          <p className="text-xs text-muted-foreground">
            Apps built by teams on Tentoro Forge and reviewed by Tentoro. Start yours from one.
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Sort">
          {SORTS.map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={sort === key ? "secondary" : "ghost"}
              className="h-8 text-xs"
              onClick={() => setSort(key)}
              aria-pressed={sort === key}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>
      {!!data?.categories.length && (
        <div className="mb-4 flex flex-wrap gap-1">
          <Button size="sm" variant={category === null ? "secondary" : "ghost"} className="h-7 text-xs" onClick={() => setCategory(null)}>
            All
          </Button>
          {data.categories.map((c) => (
            <Button key={c} size="sm" variant={category === c ? "secondary" : "ghost"} className="h-7 text-xs" onClick={() => setCategory(c)}>
              {c}
            </Button>
          ))}
        </div>
      )}
      {isLoading ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : templates.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
          {search || category
            ? "No templates in the Gallery match."
            : "Nothing in the Gallery yet. Submit one of your apps from “Your templates” — Tentoro reviews it and it appears here."}
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {templates.map((t) => (
            <GalleryCard key={t.id} tpl={t} onOpen={() => onOpen(t.id)} onOpenCreator={onOpenCreator} />
          ))}
        </div>
      )}
    </section>
  );
}
