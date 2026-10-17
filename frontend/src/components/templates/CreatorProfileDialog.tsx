"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatDate, type TemplateCardData } from "@/lib/templateGallery";
import { PersonAvatar, Stars } from "./TemplateBits";
import { GalleryCard } from "./GalleryCard";

interface CreatorProfile {
  id: string;
  name: string;
  avatar_url: string | null;
  member_since: string | null;
  organisations: string[];
  templates: TemplateCardData[];
  totals: { templates: number; uses: number; ratings: number; rating: number | null };
}

/** Who built a template, and what else they have published. */
export function CreatorProfileDialog({
  userId,
  open,
  onOpenChange,
  onOpenTemplate,
}: {
  userId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenTemplate: (templateId: string) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["template-creator", userId],
    queryFn: () => api.get<CreatorProfile>(`/api/template-creators/${userId}`),
    enabled: open && !!userId,
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        {isLoading || !data ? (
          <>
            <DialogHeader>
              <DialogTitle>Builder</DialogTitle>
              <DialogDescription>{isError ? "This profile is not available." : "Loading…"}</DialogDescription>
            </DialogHeader>
            {!isError && <Loader2 className="mx-auto my-10 h-5 w-5 animate-spin text-muted-foreground" />}
          </>
        ) : (
          <>
            <DialogHeader>
              <div className="flex items-center gap-4">
                <PersonAvatar person={data} className="h-14 w-14 text-lg" />
                <div className="min-w-0">
                  <DialogTitle className="text-xl">{data.name}</DialogTitle>
                  <DialogDescription>
                    {data.organisations.join(", ")}
                    {data.member_since && ` · On Tentoro Forge since ${formatDate(data.member_since)}`}
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>
            <dl className="grid grid-cols-3 gap-3 rounded-lg border p-3 text-center">
              <div>
                <dt className="text-[11px] text-muted-foreground">Templates</dt>
                <dd className="text-lg font-semibold">{data.totals.templates}</dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted-foreground">Times used</dt>
                <dd className="text-lg font-semibold">{data.totals.uses}</dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted-foreground">Rating</dt>
                <dd className="flex h-7 items-center justify-center">
                  <Stars value={data.totals.rating} count={data.totals.ratings} />
                </dd>
              </div>
            </dl>
            <h3 className="text-sm font-semibold">Published templates</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {data.templates.map((t) => (
                <GalleryCard key={t.id} tpl={t} onOpen={() => onOpenTemplate(t.id)} />
              ))}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
