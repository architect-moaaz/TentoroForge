"use client";

/**
 * "Connect your live app": makes the key a live app uses to send its chats to the platform, and says what to do with it.
 *
 * The full key is shown ONCE, right after it is made, in a box that stays until the person presses the button saying they have copied it
 * (or leaves the page). It is never stored by this screen, logged, or shown again; after that only its first characters are. Making a new
 * key or removing it asks first, because the old key stops working at once and the live app stops sending until it has the new one.
 */
import { useState } from "react";
import { AlertTriangle, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ago } from "@/lib/agent-insights";
import { CopyButton } from "./insights-parts";
import { useInsightsKey } from "./useInsightsKey";

/** The three lines the live app needs. Message text stays off unless the owner chooses to turn it on. */
export const envLines = (ingestUrl: string, key: string): string =>
  `FORGE_INSIGHTS_URL=${ingestUrl}\nFORGE_INSIGHTS_KEY=${key}\nFORGE_INSIGHTS_INCLUDE_TEXT=0`;

export function InsightsLiveSetup({ projectId, reason, standalone = false }: { projectId: string; reason?: string | null; standalone?: boolean }) {
  const { status, loading, busy, error, revealed, create, remove, dismiss } = useInsightsKey(projectId);
  const [confirm, setConfirm] = useState<"rotate" | "remove" | null>(null);

  const make = async () => {
    setConfirm(null);
    await create();
  };
  const take = async () => {
    setConfirm(null);
    await remove();
  };

  return (
    <div className="space-y-3 rounded-xl border bg-white p-4 shadow-sm" data-testid="insights-live-setup">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
        <div className="min-w-0">
          <h4 className="text-sm font-semibold">{standalone ? "See every chat from your live app" : "Connect a live app"}</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">
            A live app sends each assistant chat to this platform, so the numbers cover every person who uses it, not a sample, and arrive within seconds.
            The app sends an anonymous code for each person, never a name or an email, and no message text unless you turn that on.
          </p>
          {reason && (
            <p className="mt-1.5 text-xs text-muted-foreground" data-testid="insights-live-reason">
              Right now: {reason}
            </p>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="insights-key-error">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && !status && <p className="text-xs text-muted-foreground">Looking for your key…</p>}

      {status && !status.exists && !revealed && (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={() => void make()} disabled={busy}>
            Create a key
          </Button>
          <span className="text-xs text-muted-foreground">You have no key yet. The key tells the platform which project a chat belongs to.</span>
        </div>
      )}

      {status?.exists && (
        <div className="space-y-2" data-testid="insights-key-status">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Key</dt>
              <dd className="font-mono" data-testid="insights-key-prefix">{status.prefix ? `${status.prefix}…` : "(hidden)"}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Made</dt>
              <dd>{status.createdAt ? ago(status.createdAt) : "unknown"}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Last used</dt>
              <dd>{status.lastUsedAt ? ago(status.lastUsedAt) : "never yet"}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Chats received in the last 24 hours</dt>
              <dd className="tabular-nums">{status.eventsLast24h.toLocaleString("en-US")}</dd>
            </div>
          </dl>

          {confirm === null && (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setConfirm("rotate")} disabled={busy}>
                Make a new key
              </Button>
              <Button size="sm" variant="outline" onClick={() => setConfirm("remove")} disabled={busy}>
                Remove key
              </Button>
            </div>
          )}
          {confirm !== null && (
            <div role="alertdialog" aria-label={confirm === "rotate" ? "Make a new key?" : "Remove the key?"} className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900" data-testid="insights-key-confirm">
              <p>
                {confirm === "rotate"
                  ? "The old key stops working at once. Your live app will send nothing until you give it the new key."
                  : "The key stops working at once, and your live app can no longer send chats here."}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void (confirm === "rotate" ? make() : take())} disabled={busy}>
                  {confirm === "rotate" ? "Yes, make a new key" : "Yes, remove it"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setConfirm(null)}>
                  No, keep the key
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {revealed && (
        <div className="space-y-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3" data-testid="insights-key-reveal">
          <p className="text-xs font-semibold text-emerald-900">Copy your key now. It is shown only this once.</p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 break-all rounded bg-white px-2 py-1 font-mono text-[11px]" data-testid="insights-key-secret">{revealed.key}</code>
            <CopyButton text={revealed.key} label="Copy key" />
          </div>
          <div className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium">The three lines your live app needs</span>
              <CopyButton text={envLines(revealed.ingestUrl, revealed.key)} label="Copy the three lines" />
            </div>
            <pre className="overflow-x-auto rounded bg-white p-2 font-mono text-[11px] leading-relaxed" data-testid="insights-key-env">{envLines(revealed.ingestUrl, revealed.key)}</pre>
            <p className="text-[11px] text-muted-foreground">
              The last line keeps message text off. Set it to 1 only if you want the first 200 characters of a problem message sent with it.
            </p>
          </div>
          <ol className="list-decimal space-y-0.5 pl-5 text-xs" data-testid="insights-key-steps">
            <li>Paste these into your live app&apos;s environment.</li>
            <li>Apply the agent again and update the database.</li>
            <li>Restart the app.</li>
          </ol>
          <Button size="sm" variant="outline" onClick={dismiss}>
            I have copied it, hide it
          </Button>
        </div>
      )}
    </div>
  );
}
