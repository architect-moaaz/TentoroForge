"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import type { Project } from "@/types/project";

interface Template {
  slug: string;
  name: string;
  description: string | null;
  category: string;
  icon: string | null;
  complexity: string | null;
  tags: string[] | null;
  plan?: {
    tables?: string[];
    features?: string[];
  } | null;
}

interface TemplateDetailModalProps {
  template: Template | null;
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function TemplateDetailModal({
  template,
  orgId,
  open,
  onOpenChange,
}: TemplateDetailModalProps) {
  const [name, setName] = useState("");
  const router = useRouter();
  const queryClient = useQueryClient();

  const createFromTemplate = useMutation({
    mutationFn: (data: { template_slug: string; name: string }) =>
      api.post<Project>(`/api/orgs/${orgId}/projects/from-template`, data),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      onOpenChange(false);
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
  });

  if (!template) return null;

  const handleCreate = () => {
    const appName = name.trim() || template.name;
    createFromTemplate.mutate({
      template_slug: template.slug,
      name: appName,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{template.name}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <p className="text-sm text-muted-foreground">
            {template.description}
          </p>

          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{template.category}</Badge>
            {template.complexity && (
              <Badge variant="secondary">{template.complexity}</Badge>
            )}
            {template.tags?.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-xs">
                {tag}
              </Badge>
            ))}
          </div>

          {template.plan?.features && (
            <div>
              <p className="mb-2 text-sm font-medium">Features</p>
              <ul className="space-y-1">
                {template.plan.features.map((feature, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-sm text-muted-foreground"
                  >
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                    {feature}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {template.plan?.tables && (
            <div>
              <p className="mb-2 text-sm font-medium">Database Tables</p>
              <div className="flex flex-wrap gap-1">
                {template.plan.tables.map((table) => (
                  <Badge key={table} variant="outline" className="text-xs font-mono">
                    {table}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div>
            <Label htmlFor="template-app-name">App Name</Label>
            <Input
              id="template-app-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={template.name}
              className="mt-1"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={createFromTemplate.isPending}
            >
              {createFromTemplate.isPending
                ? "Creating..."
                : "Use Template"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
