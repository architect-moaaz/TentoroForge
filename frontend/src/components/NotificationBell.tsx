"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface Notification {
  id: string;
  type: string;
  title: string;
  content: string;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Only a path inside Forge is followed — never another site, whatever a row says. */
function safeLink(link: string | null) {
  return link && link.startsWith("/") && !link.startsWith("//") ? link : null;
}

/**
 * What Forge has to tell this person: a template to review, a review's
 * outcome, a new rating. The count is checked every half minute; the list is
 * read when the bell is opened.
 */
export function NotificationBell({ className }: { className?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data: count } = useQuery({
    queryKey: ["notifications", "count"],
    queryFn: () => api.get<{ unread_count: number }>("/api/notifications/count"),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const { data: items } = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: () => api.get<Notification[]>("/api/notifications?limit=30"),
    enabled: open,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useMutation({
    mutationFn: (id: string) => api.post(`/api/notifications/${id}/read`),
    onSuccess: refresh,
  });
  const markAll = useMutation({
    mutationFn: () => api.post("/api/notifications/read-all"),
    onSuccess: refresh,
  });
  const unread = count?.unread_count ?? 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          className={cn(
            "relative flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800",
            className,
          )}
        >
          <Bell className="h-3.5 w-3.5" />
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[9px] font-semibold text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <p className="text-sm font-semibold">Notifications</p>
          {unread > 0 && (
            <button
              type="button"
              onClick={() => markAll.mutate()}
              className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              <CheckCheck className="h-3 w-3" /> Mark all read
            </button>
          )}
        </div>
        <ul className="max-h-96 overflow-y-auto">
          {!items?.length ? (
            <li className="px-3 py-8 text-center text-xs text-muted-foreground">Nothing new.</li>
          ) : (
            items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => {
                    if (!n.read_at) markRead.mutate(n.id);
                    const to = safeLink(n.link);
                    if (to) {
                      setOpen(false);
                      router.push(to);
                    }
                  }}
                  className={cn(
                    "flex w-full gap-2 border-b px-3 py-2.5 text-left last:border-0 hover:bg-muted/60",
                    !n.read_at && "bg-brand-900/[0.04]",
                  )}
                >
                  <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-rose-600")} />
                  <span className="min-w-0">
                    <span className="block text-xs font-medium leading-snug">{n.title}</span>
                    <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground">{n.content}</span>
                    <span className="mt-0.5 block text-[10px] text-muted-foreground">{ago(n.created_at)}</span>
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
