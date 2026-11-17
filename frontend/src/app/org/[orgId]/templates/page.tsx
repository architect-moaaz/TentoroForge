"use client";

import { Suspense, use, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, Loader2, LayoutTemplate } from "lucide-react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { TemplateCard } from "@/components/templates/TemplateCard";
import { TemplateDetailModal } from "@/components/templates/TemplateDetailModal";
import { OrgTemplates } from "@/components/templates/OrgTemplates";
import { GallerySection } from "@/components/templates/GallerySection";
import { TemplateDetailDialog } from "@/components/templates/TemplateDetailDialog";
import { SubmitTemplateDialog } from "@/components/templates/SubmitTemplateDialog";
import { CreatorProfileDialog } from "@/components/templates/CreatorProfileDialog";

interface Template {
  slug: string;
  name: string;
  description: string | null;
  category: string;
  icon: string | null;
  complexity: string | null;
  tags: string[] | null;
  is_published: boolean;
  plan?: {
    tables?: string[];
    features?: string[];
  } | null;
}

interface TemplateListResponse {
  templates: Template[];
  categories: string[];
}

function TemplatesGallery({ orgId }: { orgId: string }) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(
    null,
  );
  const [showDetail, setShowDetail] = useState(false);
  // One template, a builder's profile, or the submit wizard: opened from a
  // card, or from a link (a notification says `?template=<id>`).
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [openTemplate, setOpenTemplate] = useState<string | null>(null);
  const [openCreator, setOpenCreator] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);
  useEffect(() => {
    const linked = params.get("template");
    if (linked && /^[0-9a-f]{32}$/.test(linked)) setOpenTemplate(linked);
    const submit = params.get("submit");
    if (submit && /^[0-9a-f]{32}$/.test(submit)) setSubmitting(submit);
  }, [params]);
  const closeTemplate = () => {
    setOpenTemplate(null);
    if (params.get("template")) router.replace(pathname);
  };

  const { data, isLoading } = useQuery({
    queryKey: ["templates", selectedCategory, search],
    queryFn: () => {
      const params = new URLSearchParams();
      if (selectedCategory) params.set("category", selectedCategory);
      if (search) params.set("search", search);
      const qs = params.toString();
      return api.get<TemplateListResponse>(
        `/api/templates${qs ? `?${qs}` : ""}`,
      );
    },
  });

  // Fetch detail when a template is selected
  const handleSelectTemplate = async (template: Template) => {
    try {
      const detail = await api.get<Template>(
        `/api/templates/${template.slug}`,
      );
      setSelectedTemplate(detail);
      setShowDetail(true);
    } catch {
      setSelectedTemplate(template);
      setShowDetail(true);
    }
  };

  const templates = data?.templates || [];
  const categories = data?.categories || [];

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="mb-1 text-2xl font-semibold text-foreground">Templates</h1>
        <p className="text-sm text-muted-foreground">
          Start from an app your organisation saved, or one shared in the Gallery
        </p>
      </div>

      <div className="mb-6">
        <div className="relative w-64">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="pl-9"
          />
        </div>
      </div>

      <OrgTemplates
        orgId={orgId}
        search={search}
        onOpen={setOpenTemplate}
        onSubmit={setSubmitting}
      />

      <GallerySection search={search} onOpen={setOpenTemplate} onOpenCreator={setOpenCreator} />

      <h2 className="mb-1 text-base font-semibold text-foreground">Starter ideas</h2>
      <p className="mb-3 text-xs text-muted-foreground">
        Outlines of common apps to describe to Smith from scratch.
      </p>
      {/* Category filter (gallery) */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1">
          <Button
            variant={selectedCategory === null ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setSelectedCategory(null)}
            className="h-8 text-xs"
          >
            All
          </Button>
          {categories.map((cat) => (
            <Button
              key={cat}
              variant={selectedCategory === cat ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setSelectedCategory(cat)}
              className="h-8 text-xs"
            >
              {cat}
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : templates.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
          <LayoutTemplate className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No templates found</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {templates.map((template) => (
            <TemplateCard
              key={template.slug}
              template={template}
              onClick={() => handleSelectTemplate(template)}
            />
          ))}
        </div>
      )}

      <TemplateDetailModal
        template={selectedTemplate}
        orgId={orgId}
        open={showDetail}
        onOpenChange={setShowDetail}
      />

      <TemplateDetailDialog
        templateId={openTemplate}
        orgId={orgId}
        open={!!openTemplate}
        onOpenChange={(o) => !o && closeTemplate()}
        onOpenCreator={(id) => setOpenCreator(id)}
        onSubmit={(id) => {
          closeTemplate();
          setSubmitting(id);
        }}
      />
      <CreatorProfileDialog
        userId={openCreator}
        open={!!openCreator}
        onOpenChange={(o) => !o && setOpenCreator(null)}
        onOpenTemplate={(id) => {
          setOpenCreator(null);
          setOpenTemplate(id);
        }}
      />
      <SubmitTemplateDialog
        templateId={submitting}
        orgId={orgId}
        open={!!submitting}
        onOpenChange={(o) => {
          if (!o) {
            setSubmitting(null);
            if (params.get("submit")) router.replace(pathname);
          }
        }}
      />
    </div>
  );
}

export default function TemplatesPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  // useSearchParams needs a Suspense boundary on a statically optimised page.
  return (
    <Suspense fallback={null}>
      <TemplatesGallery orgId={orgId} />
    </Suspense>
  );
}
