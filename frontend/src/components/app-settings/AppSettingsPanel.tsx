"use client";

/**
 * App settings — the app's own settings, one section per concern. Domains is
 * the first: the same panel the Publish dialog's Custom domain card shows.
 */
import { Bot, Globe, Rocket } from "lucide-react";

import { AssistantsSection } from "@/components/app-settings/AssistantsSection";
import { DomainsPanel } from "@/components/deploy/DomainsPanel";
import { PublishTargetSwitch, SidesSummary, usePublishStatus } from "@/components/deploy/PublishSides";
import { useAppSettingsStore, type AppSettingsSection } from "@/stores/appSettings";

const SECTIONS: { id: AppSettingsSection; label: string; icon: typeof Globe }[] = [
  { id: "publishing", label: "Publishing", icon: Rocket },
  { id: "domains", label: "Domains", icon: Globe },
  { id: "assistants", label: "AI assistants", icon: Bot },
];

/** Test and Production: where Publish sends the app, and what each side runs. */
function PublishingSection({ projectId }: { projectId: string }) {
  const { data, isLoading, error } = usePublishStatus(projectId);
  if (isLoading) return <p className="text-sm text-slate-500">Reading where the app is published…</p>;
  if (error || !data) return <p className="text-sm text-red-700 dark:text-red-300">Could not read where the app is published.</p>;
  return (
    <div className="space-y-4">
      <PublishTargetSwitch projectId={projectId} value={data.target} />
      <SidesSummary status={data} />
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
        <li>
          <b>Test</b>: Publish puts the app at its own address with its own demo data. The live app, its data and its
          users are not touched. Payments use Stripe test mode, or a stand-in that charges nobody; email goes only to
          your organisation&rsquo;s members; every page says &ldquo;Test version&rdquo;.
        </li>
        <li>
          <b>Production</b>: Publish updates the live app, at its own address and domains, with its real data.
        </li>
        <li>
          From Test, <b>Promote to Production</b> in the Publish dialog sends exactly what Test runs to the live app.
        </li>
      </ul>
    </div>
  );
}

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
        {section === "publishing" && (
          <section className="mx-auto max-w-2xl space-y-4">
            <header>
              <h3 className="text-base font-semibold">Publishing</h3>
              <p className="text-sm text-slate-500">Where Publish sends the app: its test version, or the live app.</p>
            </header>
            <PublishingSection projectId={projectId} />
          </section>
        )}
        {section === "assistants" && (
          <section className="mx-auto max-w-2xl space-y-4">
            <header>
              <h3 className="text-base font-semibold">AI assistants</h3>
              <p className="text-sm text-slate-500">Whether Claude, or any MCP client, may use this app for its people.</p>
            </header>
            <AssistantsSection projectId={projectId} />
          </section>
        )}
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
