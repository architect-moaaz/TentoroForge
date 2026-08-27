"use client";

import { Check, Link2 } from "lucide-react";
import type { DesignTemplate } from "@/stores/chat";

/** A token-driven mini preview drawn from the template's actual values, so what
 *  you see is what compiles. */
function Preview({ t }: { t: DesignTemplate }) {
  const dark = t.palette.mode === "dark" || t.shell?.tone === "dark";
  const bg = dark ? "#0F172A" : "#FFFFFF";
  const card = dark ? "#1E293B" : "#FFFFFF";
  const cardBorder = dark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)";
  const text = dark ? "#E2E8F0" : "#0F172A";
  const sideBg = t.palette.sidebarBg || (t.shell?.frame !== "topbar" ? "#0B1220" : (dark ? "#111827" : "#F8FAFC"));
  const accent = t.palette.accent || t.palette.primary;
  const rad =
    t.tokens?.radiusScale === "sharp" ? 3 :
    t.tokens?.radiusScale === "pill" ? 12 :
    t.tokens?.radiusScale === "rounded" ? 9 : 6;
  const topbar = t.shell?.frame === "topbar";

  return (
    <div style={{ height: 116, borderRadius: 10, overflow: "hidden", background: bg, display: "flex", flexDirection: topbar ? "column" : "row", border: `0.5px solid ${cardBorder}` }}>
      {topbar ? (
        <div style={{ height: 18, background: sideBg, display: "flex", alignItems: "center", gap: 6, padding: "0 8px" }}>
          {[0, 1, 2].map((i) => <div key={i} style={{ width: 14, height: 4, borderRadius: 2, background: i === 0 ? accent : text, opacity: i === 0 ? 1 : 0.4 }} />)}
        </div>
      ) : (
        <div style={{ width: 24, background: sideBg, padding: "8px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          {[0, 1, 2].map((i) => <div key={i} style={{ width: 12, height: 4, borderRadius: 2, background: i === 0 ? accent : "#94A3B8", opacity: i === 0 ? 1 : 0.5 }} />)}
        </div>
      )}
      <div style={{ flex: 1, padding: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ width: 40, height: 6, borderRadius: 3, background: text, opacity: 0.85 }} />
          <div style={{ width: 22, height: 8, borderRadius: rad / 2, background: accent }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
          {[0, 1].map((i) => <div key={i} style={{ height: 18, borderRadius: Math.min(rad, 8), background: card, border: `0.5px solid ${cardBorder}` }} />)}
        </div>
        <div style={{ height: 28, borderRadius: Math.min(rad, 8), background: card, border: `0.5px solid ${cardBorder}`, padding: 5 }}>
          <div style={{ width: "70%", height: 4, borderRadius: 2, background: text, opacity: 0.25, marginBottom: 4 }} />
          <div style={{ width: "50%", height: 4, borderRadius: 2, background: text, opacity: 0.15 }} />
        </div>
      </div>
    </div>
  );
}

export function TemplateGallery({
  templates,
  selectedId,
  onSend,
  disabled,
}: {
  templates: DesignTemplate[];
  selectedId: string | null;
  onSend: (message: string) => void;
  disabled?: boolean;
}) {
  if (templates.length === 0) return null;
  const selected = templates.find((t) => t.id === selectedId);
  return (
    <div className="px-4 md:px-6 py-3">
      <div className="mx-auto max-w-3xl">
        {selected ? (
          <div className="mb-2 flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
            <Check className="h-3.5 w-3.5" />
            Design set to <span className="font-semibold">{selected.name}</span> — now click
            <span className="font-semibold">“Begin Quest”</span> above to build with this look.
          </div>
        ) : (
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Pick a look — this is how the app will be styled. Or just approve the plan to use the default.
          </p>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {templates.map((t) => {
            const isSel = selectedId === t.id;
            return (
              <div
                key={t.id}
                className={`rounded-xl border bg-card p-2.5 transition-colors ${
                  isSel ? "border-2 border-primary" : "border-border/70"
                }`}
              >
                <Preview t={t} />
                <div className="px-0.5 pt-2">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium">{t.name}</p>
                    {isSel && <Check className="h-3.5 w-3.5 text-primary" />}
                  </div>
                  {t.vibe && <p className="text-[11px] text-muted-foreground">{t.vibe}</p>}
                  <div className="my-2 flex gap-1.5">
                    {[t.palette.primary, t.palette.accent, t.palette.sidebarBg || "#334155"].map((c, i) => (
                      <span key={i} className="h-4 w-4 rounded" style={{ background: c, border: "0.5px solid rgba(0,0,0,.1)" }} />
                    ))}
                  </div>
                  {t.provenance && (
                    <p className="mb-2 truncate text-[10px] text-muted-foreground">
                      <Link2 className="mr-0.5 inline h-2.5 w-2.5" />
                      {t.provenance}
                    </p>
                  )}
                  <button
                    onClick={() => onSend(`[SELECT_TEMPLATE:${t.id}]`)}
                    disabled={disabled}
                    className={`w-full rounded-lg border px-2 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                      isSel ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted"
                    }`}
                  >
                    {isSel ? "Selected" : "Use this look"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
