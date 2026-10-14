"use client";

/**
 * App settings — the app's own settings, one section per concern. Domains is
 * the first: the same panel the Publish dialog's Custom domain card shows.
 */
import { Globe } from "lucide-react";

import { DomainsPanel } from "@/components/deploy/DomainsPanel";
import { useAppSettingsStore, type AppSettingsSection } from "@/stores/appSettings";

const SECTIONS: { id: AppSettingsSection; label: string; icon: typeof Globe }[] = [
  { id: "domains", label: "Domains", icon: Globe },
];

export function AppSettingsPanel({ projectId }: { projectId: string }) {
  const section = useAppSettingsStore((s) => s.section);
  const open = useAppSettingsStore((s) => s.open);

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <nav aria-label="App settings" className="flex shrink-0 gap-1 border-b border-slate-200 p-3 md:w-48 md:flex-col md:border-b-0 md:border-r dark:border-slate-800">
        <h2 className="sr-only">App settings</h2>
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => open(id)}
            aria-current={section === id ? "page" : undefined}
            className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm ${
              section === id
                ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {section === "domains" && (
          <section className="mx-auto max-w-2xl space-y-4">
            <header>
              <h3 className="text-base font-semibold">Domains</h3>
              <p className="text-sm text-slate-500">Where people open the app.</p>
            </header>
            <DomainsPanel projectId={projectId} />
          </section>
        )}
      </div>
    </div>
  );
}
