"use client";

import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Loader2, LayoutTemplate } from "lucide-react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { TemplateCard } from "@/components/templates/TemplateCard";
import { TemplateDetailModal } from "@/components/templates/TemplateDetailModal";

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
          Start with a pre-built template and customize it to your needs
        </p>
      </div>

      {/* Search + category filter */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative w-64">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="pl-9"
          />
        </div>

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
    </div>
  );
}

export default function TemplatesPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <TemplatesGallery orgId={orgId} />;
}
