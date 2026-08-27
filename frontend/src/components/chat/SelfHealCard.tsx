"use client";

import {
  Wrench,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  FileCode2,
  GitCommit,
  Loader2,
} from "lucide-react";

/**
 * SelfHealCard — SH-1
 *
 * Rich variant of the plain-markdown self-heal bubble. Renders one of four
 * states from `metadata.status`:
 *   • in_progress → "🔧 fixing…" with a spinner (shown the moment heal
 *     starts, before Smith produces any output).
 *   • resolved    → files touched, commit sha, revert hint.
 *   • asked       → Smith needed clarification; question shown verbatim.
 *   • failed      → attempt count, why-not, "will retry" note if attempts remain.
 *
 * Wired in ChatMessage.tsx when `metadata.self_heal === true` AND
 * `metadata.status` is present. Backwards-compatible: heal messages
 * without a status field still fall through to the classic markdown bubble.
 */

type SelfHealStatus = "in_progress" | "resolved" | "asked" | "failed";

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
}

interface Props {
  metadata: SelfHealMetadata;
  createdAt?: string;
}

export function SelfHealCard({ metadata, createdAt }: Props) {
  const status = metadata.status;
  const theme = _themeFor(status);
  const anchorLabel =
    metadata.node_id ||
    metadata.source_file ||
    metadata.workflow_id ||
    metadata.page_route ||
    "the app";

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header — status + anchor + attempt */}
      <div className={`border-b ${theme.headerBg} px-4 py-3`}>
        <div className="flex items-center gap-2">
          {theme.icon}
          <h3 className={`font-semibold text-sm ${theme.headerText}`}>
            {theme.title}
          </h3>
          {metadata.attempt != null && metadata.max_attempts != null && (
            <span className="ml-auto text-[10px] text-muted-foreground">
              attempt {metadata.attempt} of {metadata.max_attempts}
            </span>
          )}
        </div>
        {metadata.error_message && (
          <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
            {metadata.error_message}
          </p>
        )}
      </div>

      <div className="divide-y text-xs">
        {/* Anchor row — where the error happened */}
        <div className="px-4 py-2.5">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-muted-foreground">
            <FileCode2 className="h-3 w-3" />
            Location
          </div>
          <div className="space-y-0.5">
            {metadata.node_id && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Node:</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                  {metadata.node_id}
                </code>
              </div>
            )}
            {metadata.workflow_id && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Workflow:</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                  {metadata.workflow_id}
                </code>
              </div>
            )}
            {metadata.source_file && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">File:</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                  {metadata.source_file}
                </code>
              </div>
            )}
            {metadata.page_route && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Route:</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                  {metadata.page_route}
                </code>
              </div>
            )}
            {!metadata.node_id &&
              !metadata.workflow_id &&
              !metadata.source_file &&
              !metadata.page_route && (
                <span className="text-muted-foreground">{anchorLabel}</span>
              )}
          </div>
        </div>

        {/* In-progress state — just the note */}
        {status === "in_progress" && (
          <div className="px-4 py-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Smith is reading the error, loading the offending file, and
              planning a targeted edit…
            </div>
          </div>
        )}

        {/* Asked state — Smith needs input */}
        {status === "asked" && metadata.question && (
          <div className="px-4 py-2.5 bg-amber-50/40">
            <div className="mb-1 flex items-center gap-1.5 font-medium text-amber-800">
              <HelpCircle className="h-3 w-3" />
              Smith needs your input
            </div>
            <p className="text-amber-900">{metadata.question}</p>
          </div>
        )}

        {/* Resolved / failed — files touched + commit */}
        {(status === "resolved" || status === "failed") &&
          metadata.edited_paths &&
          metadata.edited_paths.length > 0 && (
            <div className="px-4 py-2.5">
              <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
                <FileCode2 className="h-3 w-3" />
                Files changed ({metadata.edited_paths.length})
              </div>
              <ul className="space-y-0.5">
                {metadata.edited_paths.slice(0, 6).map((p) => (
                  <li key={p} className="flex items-start gap-1.5">
                    <span className="text-muted-foreground">•</span>
                    <code className="rounded bg-muted px-1.5 py-0.5 text-[10px] break-all">
                      {p}
                    </code>
                  </li>
                ))}
                {metadata.edited_paths.length > 6 && (
                  <li className="text-[10px] text-muted-foreground pl-3">
                    …and {metadata.edited_paths.length - 6} more
                  </li>
                )}
              </ul>
            </div>
          )}

        {status === "failed" &&
          (!metadata.edited_paths || metadata.edited_paths.length === 0) && (
            <div className="px-4 py-2.5 bg-red-50/40">
              <div className="flex items-center gap-1.5 text-red-800">
                <AlertTriangle className="h-3 w-3" />
                Smith could not localize a fix on this attempt.
                {metadata.attempt != null &&
                  metadata.max_attempts != null &&
                  metadata.attempt < metadata.max_attempts && (
                    <span className="text-red-700/80">
                      Will retry (up to {metadata.max_attempts}).
                    </span>
                  )}
              </div>
            </div>
          )}

        {/* Commit footer — only when a commit landed */}
        {metadata.commit && (
          <div className="px-4 py-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <GitCommit className="h-3 w-3" />
              Committed as
              <code className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-800">
                {metadata.commit.slice(0, 8)}
              </code>
              <span className="text-[10px]">
                — <code className="text-[10px]">git revert</code> to undo
              </span>
            </div>
          </div>
        )}
      </div>

      {createdAt && (
        <div className="border-t px-4 py-2 text-[10px] text-muted-foreground">
          {new Date(createdAt).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </div>
      )}
    </div>
  );
}


function _themeFor(status: SelfHealStatus) {
  switch (status) {
    case "in_progress":
      return {
        headerBg: "bg-gradient-to-r from-sky-50 to-blue-50",
        headerText: "text-sky-900",
        icon: <Loader2 className="h-4 w-4 text-sky-500 animate-spin" />,
        title: "Self-heal in progress",
      };
    case "resolved":
      return {
        headerBg: "bg-gradient-to-r from-emerald-50 to-green-50",
        headerText: "text-emerald-900",
        icon: <CheckCircle2 className="h-4 w-4 text-emerald-600" />,
        title: "Runtime error healed",
      };
    case "asked":
      return {
        headerBg: "bg-gradient-to-r from-amber-50 to-yellow-50",
        headerText: "text-amber-900",
        icon: <HelpCircle className="h-4 w-4 text-amber-600" />,
        title: "Self-heal needs input",
      };
    case "failed":
    default:
      return {
        headerBg: "bg-gradient-to-r from-red-50 to-rose-50",
        headerText: "text-red-900",
        icon: <Wrench className="h-4 w-4 text-red-600" />,
        title: "Self-heal could not fix",
      };
  }
}
