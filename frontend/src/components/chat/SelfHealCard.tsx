"use client";

import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  FileCode2,
  GitCommit,
  HelpCircle,
  Hourglass,
  Loader2,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * SelfHealCard — an error the running app hit, and what Smith did about it.
 *
 * One card per heal, updated in place: it opens as "Fixing…" the moment the
 * heal starts and becomes the outcome when Smith finishes. Read top to
 * bottom it answers four questions in order — what broke, where, what Smith
 * did, and what happens next — so the outcome never contradicts itself
 * ("no fix produced" above "nothing needed doing" above "still open").
 *
 * Drawn from `metadata.status`:
 *   • in_progress → spinner, "Fixing an error in …"
 *   • resolved    → tick, the files changed and the commit
 *   • asked       → Smith's question
 *   • untried     → a change made that no try has proven yet
 *   • failed      → not fixed yet; whether another try will come
 */

type SelfHealStatus = "in_progress" | "resolved" | "untried" | "asked" | "failed";

export interface SelfHealMetadata {
  self_heal: true;
  status: SelfHealStatus;
  exception_id?: string;
  exception_kind?: string;
  error_message?: string;
  workflow_id?: string | null;
  node_id?: string | null;
  page_route?: string | null;
  source_file?: string | null;
  attempt?: number;
  max_attempts?: number;
  edited_paths?: string[];
  commit?: string | null;
  question?: string;
  /** Smith's own account of what it found or did. */
  summary?: string;
}

interface Props {
  metadata: SelfHealMetadata;
  createdAt?: string | number;
}

/** Where the error happened, in the words the app uses for it. */
export function healPlace(m: SelfHealMetadata): string {
  if (m.page_route) return `the ${m.page_route} screen`;
  if (m.workflow_id) return `the ${m.workflow_id} process`;
  if (m.source_file) return m.source_file.split("/").pop() || m.source_file;
  if (m.node_id) return m.node_id;
  return "the app";
}

const TONE: Record<SelfHealStatus, { badge: string; icon: ReactNode; title: (place: string) => string }> = {
  in_progress: {
    badge: "bg-sky-500 text-white",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    title: (p) => `Fixing an error in ${p}`,
  },
  resolved: {
    badge: "bg-emerald-500 text-white",
    icon: <Check className="h-3.5 w-3.5" />,
    title: (p) => `Fixed an error in ${p}`,
  },
  untried: {
    badge: "bg-amber-500 text-white",
    icon: <Hourglass className="h-3.5 w-3.5" />,
    title: (p) => `Changed, not yet proven: an error in ${p}`,
  },
  asked: {
    badge: "bg-amber-500 text-white",
    icon: <HelpCircle className="h-3.5 w-3.5" />,
    title: (p) => `A question before fixing ${p}`,
  },
  failed: {
    badge: "bg-rose-500 text-white",
    icon: <TriangleAlert className="h-3.5 w-3.5" />,
    title: (p) => `Not fixed yet: an error in ${p}`,
  },
};

export function SelfHealCard({ metadata, createdAt }: Props) {
  const status: SelfHealStatus = metadata.status in TONE ? metadata.status : "failed";
  const tone = TONE[status];
  const [errorOpen, setErrorOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);

  const files = metadata.edited_paths ?? [];
  const attempt = metadata.attempt ?? null;
  const max = metadata.max_attempts ?? null;
  const triesLeft = attempt != null && max != null ? Math.max(0, max - attempt) : null;
  const where = [
    metadata.workflow_id && { label: "Process", value: metadata.workflow_id },
    metadata.node_id && { label: "Step", value: metadata.node_id },
    metadata.page_route && { label: "Screen", value: metadata.page_route },
    metadata.source_file && { label: "File", value: metadata.source_file },
  ].filter(Boolean) as { label: string; value: string }[];
  const when =
    createdAt != null
      ? new Date(createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : null;
  const error = (metadata.error_message || "").trim();

  return (
    <div data-testid="self-heal-card" data-status={status}>
      {/* What happened, in one line. */}
      <div className="flex items-start gap-3">
        <span className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", tone.badge)}>
          {tone.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold leading-tight">{tone.title(healPlace(metadata))}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>Self-heal</span>
            {attempt != null && max != null && (
              <>
                <span aria-hidden>·</span>
                <span>Try {attempt} of {max}</span>
              </>
            )}
            {when && (
              <>
                <span aria-hidden>·</span>
                <time>{when}</time>
              </>
            )}
          </div>
        </div>
      </div>

      {/* What broke. */}
      {error && (
        <button
          type="button"
          onClick={() => setErrorOpen((o) => !o)}
          className="mt-3 block w-full rounded-lg border border-rose-200/70 bg-rose-50/60 px-3 py-2 text-left dark:border-rose-900/60 dark:bg-rose-950/30"
          title={errorOpen ? "Show less" : "Show the whole error"}
        >
          <div className="text-[11px] font-medium uppercase tracking-wide text-rose-700/80 dark:text-rose-300/80">
            The error
          </div>
          <code className={cn(
            "mt-0.5 block whitespace-pre-wrap break-words font-mono text-xs text-foreground",
            !errorOpen && "line-clamp-2",
          )}>
            {error}
          </code>
        </button>
      )}

      {/* Where. */}
      {where.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {where.map((w) => (
            <span
              key={w.label}
              className="inline-flex max-w-full items-center gap-1 rounded-md border bg-background px-2 py-0.5 text-[11px]"
            >
              <span className="text-muted-foreground">{w.label}</span>
              <code className="truncate font-mono text-foreground">{w.value}</code>
            </span>
          ))}
        </div>
      )}

      {/* What Smith did, or is doing. */}
      {status === "in_progress" && (
        <p className="mt-3 text-sm text-muted-foreground">
          Smith is reading the error and the code it came from. This card updates when it is done.
        </p>
      )}
      {status === "asked" && metadata.question && (
        <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2.5 text-sm dark:bg-amber-950/30">
          <div className="text-xs font-semibold text-amber-800 dark:text-amber-200">Smith asks</div>
          <p className="mt-0.5 text-foreground">{metadata.question}</p>
        </div>
      )}
      {status !== "in_progress" && metadata.summary && (
        <div className="prose prose-sm mt-3 max-w-none text-sm leading-relaxed text-foreground [&_p]:my-1 [&_p:first-child]:mt-0 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:text-[0.85em] [&_code]:before:content-none [&_code]:after:content-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{metadata.summary}</ReactMarkdown>
        </div>
      )}

      {files.length > 0 && (
        <div className="mt-3 flex gap-3 rounded-lg bg-blue-50 px-3 py-2.5 dark:bg-blue-950/40">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200">
            <FileCode2 className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-foreground">
                {files.length === 1 ? "1 file changed" : `${files.length} files changed`}
              </span>
              {metadata.commit && (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <GitCommit className="h-3 w-3" />
                  <code className="font-mono">{metadata.commit.slice(0, 8)}</code>
                </span>
              )}
            </div>
            <ul className="mt-0.5 space-y-0.5 text-muted-foreground">
              {(filesOpen ? files : files.slice(0, 3)).map((f) => (
                <li key={f} className="truncate font-mono" title={f}>{f}</li>
              ))}
            </ul>
            {files.length > 3 && (
              <button
                type="button"
                onClick={() => setFilesOpen((o) => !o)}
                className="mt-1 text-[11px] font-medium text-blue-700 hover:underline dark:text-blue-300"
              >
                {filesOpen ? "Show fewer" : `Show all ${files.length}`}
              </button>
            )}
          </div>
        </div>
      )}

      {/* What happens next. */}
      {status === "untried" && (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
          <RotateCcw className="mt-0.5 h-3 w-3 shrink-0" />
          The change is in place. The error stays open until the app runs this again without it.
        </p>
      )}
      {status === "failed" && (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
          <RotateCcw className="mt-0.5 h-3 w-3 shrink-0" />
          {triesLeft == null
            ? "The error is still open. Smith tries again if it happens again."
            : triesLeft > 0
            ? `The error is still open. Smith tries again if it happens again (${triesLeft} ${triesLeft === 1 ? "try" : "tries"} left).`
            : "That was the last automatic try. The error stays open; ask Smith in chat to look at it."}
        </p>
      )}
    </div>
  );
}
