"use client";

import { useState } from "react";
import { ImageIcon, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  STATUS_LABEL,
  STATUS_TONE,
  initials,
  shotPath,
  useAuthedImage,
  type TemplatePerson,
  type TemplateStatus,
} from "@/lib/templateGallery";

export function StatusBadge({ status, className }: { status: TemplateStatus; className?: string }) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        STATUS_TONE[status],
        className,
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/** A rating, drawn: whole and half stars, with the count beside it. */
export function Stars({
  value,
  count,
  size = "sm",
}: {
  value: number | null;
  count?: number;
  size?: "sm" | "md";
}) {
  const px = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  if (value == null) {
    return <span className="text-[11px] text-muted-foreground">No ratings yet</span>;
  }
  return (
    <span className="inline-flex items-center gap-1" aria-label={`Rated ${value} of 5`}>
      <span className="inline-flex">
        {[1, 2, 3, 4, 5].map((i) => {
          const fill = Math.max(0, Math.min(1, value - (i - 1)));
          return (
            <span key={i} className={cn("relative", px)}>
              <Star className={cn("absolute inset-0 text-slate-300 dark:text-slate-600", px)} />
              <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
                <Star className={cn("fill-amber-400 text-amber-400", px)} />
              </span>
            </span>
          );
        })}
      </span>
      <span className="text-[11px] font-medium text-foreground">{value.toFixed(1)}</span>
      {count != null && <span className="text-[11px] text-muted-foreground">({count})</span>}
    </span>
  );
}

/** Choosing a rating: five buttons, keyboard-reachable, the hovered one previewed. */
export function StarInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [hover, setHover] = useState(0);
  const shown = hover || value;
  return (
    <div className="inline-flex" role="radiogroup" aria-label="Your rating" onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((i) => (
        <button
          key={i}
          type="button"
          role="radio"
          aria-checked={value === i}
          aria-label={`${i} star${i === 1 ? "" : "s"}`}
          onMouseEnter={() => setHover(i)}
          onClick={() => onChange(i)}
          className="p-0.5"
        >
          <Star
            className={cn(
              "h-6 w-6 transition-colors",
              i <= shown ? "fill-amber-400 text-amber-400" : "text-slate-300 dark:text-slate-600",
            )}
          />
        </button>
      ))}
    </div>
  );
}

export function Shot({
  templateId,
  shotId,
  alt,
  className,
}: {
  templateId: string;
  shotId: string | null | undefined;
  alt: string;
  className?: string;
}) {
  const url = useAuthedImage(shotId ? shotPath(templateId, shotId) : null);
  if (!shotId) {
    return (
      <div className={cn("flex items-center justify-center bg-muted text-muted-foreground", className)}>
        <ImageIcon className="h-6 w-6" />
      </div>
    );
  }
  return url ? (
    // eslint-disable-next-line @next/next/no-img-element -- a blob URL, not an optimisable asset
    <img src={url} alt={alt} className={cn("object-cover object-top", className)} />
  ) : (
    <div className={cn("animate-pulse bg-muted", className)} />
  );
}

export function PersonAvatar({
  person,
  className,
}: {
  person: Pick<TemplatePerson, "name" | "avatar_url"> | null | undefined;
  className?: string;
}) {
  if (person?.avatar_url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- an external avatar URL
      <img
        src={person.avatar_url}
        alt=""
        className={cn("h-6 w-6 rounded-full object-cover", className)}
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-full bg-brand-900/10 text-[10px] font-semibold text-brand-900 dark:bg-white/10 dark:text-white",
        className,
      )}
    >
      {initials(person?.name)}
    </span>
  );
}
