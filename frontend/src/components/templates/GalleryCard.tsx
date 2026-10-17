"use client";

import { Users } from "lucide-react";
import { countsLine, formatDate, type TemplateCardData } from "@/lib/templateGallery";
import { PersonAvatar, Shot, Stars, StatusBadge } from "./TemplateBits";

/**
 * A template as the Gallery shows it: its cover, who built it and when, its
 * version, how often it has been used and how people rated it. The builder's
 * name opens their profile; the rest of the card opens the template.
 */
export function GalleryCard({
  tpl,
  onOpen,
  onOpenCreator,
  showStatus = false,
}: {
  tpl: TemplateCardData;
  onOpen: () => void;
  onOpenCreator?: (userId: string) => void;
  showStatus?: boolean;
}) {
  const counts = countsLine(tpl.summary?.counts);
  return (
    <article
      className="group flex flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-md"
      data-template={tpl.id}
    >
      <button type="button" onClick={onOpen} className="relative block text-left" aria-label={`Open ${tpl.name}`}>
        <Shot
          templateId={tpl.id}
          shotId={tpl.screenshots[0]?.id}
          alt={`${tpl.name} — cover`}
          className="aspect-[16/10] w-full border-b"
        />
        <span className="absolute right-2 top-2 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-medium text-white">
          v{tpl.version}
        </span>
        {showStatus && <StatusBadge status={tpl.status} className="absolute left-2 top-2" />}
      </button>
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <button type="button" onClick={onOpen} className="text-left">
          <h3 className="line-clamp-1 text-sm font-semibold text-foreground group-hover:underline">{tpl.name}</h3>
          {tpl.description && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{tpl.description}</p>}
        </button>
        {counts && <p className="text-[11px] text-foreground/70">{counts}</p>}
        <div className="flex items-center justify-between gap-2">
          <Stars value={tpl.rating} count={tpl.ratings} />
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground" title="Apps started from it">
            <Users className="h-3 w-3" /> {tpl.uses} use{tpl.uses === 1 ? "" : "s"}
          </span>
        </div>
        <div className="mt-auto flex items-center gap-2 border-t pt-2.5">
          {tpl.creator ? (
            <button
              type="button"
              onClick={() => tpl.creator?.id && onOpenCreator?.(tpl.creator.id)}
              disabled={!onOpenCreator}
              className="flex min-w-0 items-center gap-1.5 text-left enabled:hover:underline"
              aria-label={`View ${tpl.creator.name}'s profile`}
            >
              <PersonAvatar person={tpl.creator} className="h-5 w-5" />
              <span className="truncate text-[11px] font-medium">{tpl.creator.name}</span>
            </button>
          ) : (
            <span className="text-[11px] text-muted-foreground">Unknown builder</span>
          )}
          <span className="ml-auto shrink-0 text-[11px] text-muted-foreground" title="When it was built">
            {formatDate(tpl.created_at)}
          </span>
        </div>
      </div>
    </article>
  );
}
