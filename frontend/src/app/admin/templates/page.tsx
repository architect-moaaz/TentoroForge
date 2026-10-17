"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDate, STATUS_LABEL, type TemplateCardData, type TemplateStatus } from "@/lib/templateGallery";
import { PersonAvatar, Shot, Stars, StatusBadge } from "@/components/templates/TemplateBits";
import { TemplateDetailDialog } from "@/components/templates/TemplateDetailDialog";

const TABS: TemplateStatus[] = ["pending", "approved", "rejected", "removed"];

/**
 * Tentoro's review queue for the Templates Gallery. Waiting requests come
 * first, oldest at the top; opening one shows everything the template holds,
 * its checks and history, a test copy to try, and the decision.
 */
function TemplateRequests() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [status, setStatus] = useState<TemplateStatus | "all">("pending");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    const linked = params.get("request");
    if (linked && /^[0-9a-f]{32}$/.test(linked)) setOpen(linked);
  }, [params]);

  const { data, isLoading } = useQuery({
    queryKey: ["template-requests", status],
    queryFn: () =>
      api.get<{ requests: TemplateCardData[]; counts: Record<TemplateStatus, number> }>(
        `/api/admin/template-requests?status=${status}`,
      ),
  });
  const rows = data?.requests ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Template requests</h1>
        <p className="text-sm text-muted-foreground">
          Templates teams asked to share in the Gallery. Nothing is public until it is approved here;
          the builder is told of every decision.
        </p>
      </div>
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Status">
        {[...TABS, "all" as const].map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={status === s}
            onClick={() => setStatus(s)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium",
              status === s ? "bg-brand-900 text-white" : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "all" ? "All" : STATUS_LABEL[s]}
            {s !== "all" && data?.counts && <span className="ml-1.5 tabular-nums opacity-80">{data.counts[s] ?? 0}</span>}
          </button>
        ))}
      </div>
      <div className="overflow-hidden rounded-lg border bg-white dark:bg-slate-900">
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : rows.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            {status === "pending" ? "No templates are waiting for review." : "None."}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Template</th>
                <th className="px-3 py-2 font-medium">Built by</th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">Holds</th>
                <th className="px-3 py-2 font-medium">Submitted</th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr
                  key={t.id}
                  onClick={() => setOpen(t.id)}
                  className="cursor-pointer border-b last:border-0 hover:bg-muted/40"
                  data-request={t.id}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Shot templateId={t.id} shotId={t.screenshots[0]?.id} alt="" className="h-10 w-16 shrink-0 rounded border" />
                      <div className="min-w-0">
                        <p className="truncate font-medium">{t.name} <span className="text-xs text-muted-foreground">v{t.version}</span></p>
                        <p className="truncate text-xs text-muted-foreground">{t.category || "—"}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <PersonAvatar person={t.creator} />
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium">{t.creator?.name || t.created_by_name || "—"}</p>
                        <p className="truncate text-[11px] text-muted-foreground">{t.org_name}</p>
                      </div>
                    </div>
                  </td>
                  <td className="hidden px-3 py-2.5 text-xs text-muted-foreground md:table-cell">
                    {t.summary.counts?.pages ?? 0} screens · {t.summary.counts?.entities ?? 0} data models ·{" "}
                    {t.summary.counts?.workflows ?? 0} workflows · {t.screenshots.length} pictures
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">{formatDate(t.submitted_at) || "—"}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col items-start gap-1">
                      <StatusBadge status={t.status} />
                      {t.status === "approved" && (
                        <span className="text-[11px] text-muted-foreground">
                          {t.uses} uses · <Stars value={t.rating} count={t.ratings} />
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <TemplateDetailDialog
        templateId={open}
        open={!!open}
        onOpenChange={(o) => {
          if (!o) {
            setOpen(null);
            if (params.get("request")) router.replace(pathname);
          }
        }}
      />
    </div>
  );
}

export default function AdminTemplatesPage() {
  return (
    <Suspense fallback={null}>
      <TemplateRequests />
    </Suspense>
  );
}
