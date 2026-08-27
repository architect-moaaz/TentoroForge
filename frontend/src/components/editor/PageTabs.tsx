"use client";
import { X } from "lucide-react";

interface Props {
  openPages: string[];
  activePage: string;
  onActivate: (slug: string) => void;
  onClose: (slug: string) => void;
}

export function PageTabs({ openPages, activePage, onActivate, onClose }: Props) {
  if (openPages.length === 0) return <div className="h-7 border-b bg-muted/20 flex-shrink-0" />;
  return (
    <div role="tablist" aria-label="Open pages" className="h-7 px-2 flex items-end gap-0.5 bg-muted/20 border-b overflow-x-auto flex-shrink-0">
      {openPages.map((slug, i) => {
        const isActive = slug === activePage;
        return (
          <div
            key={slug}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(slug); }
              else if (e.key === "ArrowRight") { e.preventDefault(); onActivate(openPages[(i + 1) % openPages.length]); }
              else if (e.key === "ArrowLeft") { e.preventDefault(); onActivate(openPages[(i - 1 + openPages.length) % openPages.length]); }
              else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); onClose(slug); }
            }}
            className={`group h-6 pl-2 pr-1 rounded-t flex items-center gap-1.5 text-[11px] cursor-pointer select-none focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 ${
              isActive
                ? "bg-background border border-b-transparent border-border -mb-px"
                : "hover:bg-background/50"
            }`}
            onClick={() => onActivate(slug)}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500 flex-shrink-0" />
            <span className={isActive ? "font-medium" : "text-muted-foreground"}>{slug}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onClose(slug); }}
              className="opacity-0 group-hover:opacity-100 h-4 w-4 grid place-items-center rounded hover:bg-muted ml-0.5 flex-shrink-0"
              aria-label={`Close ${slug}`}
            >
              <X size={10} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
