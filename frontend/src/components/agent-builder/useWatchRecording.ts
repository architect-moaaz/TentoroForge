"use client";

/**
 * Recording the next X chats from Watch live: the part that holds it.
 *
 * It lives in the builder (next to useAgentWatch), not in the Watch panel, so recording carries on while the builder looks at Find
 * problems or the Test view, and chats that finish meanwhile are still kept. What is kept is also put in the browser's storage, one
 * recording per project, so a page reload does not lose a recording that took twenty chats to make. If the browser will not store it
 * (private window, storage full, blocked) everything still works for as long as the page is open.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { WatchState } from "@/lib/agent-watch";
import { clampWant, clear as clearRecording, readRecording, start as startRecording, stop as stopRecording, summarise, take, type Recording } from "@/lib/agent-recording";

const keyOf = (projectId: string) => `forge.watch.recording.${projectId}`;

function load(projectId: string): Recording {
  try {
    return readRecording(window.localStorage.getItem(keyOf(projectId)));
  } catch {
    return readRecording(null);
  }
}

function save(projectId: string, rec: Recording) {
  try {
    window.localStorage.setItem(keyOf(projectId), JSON.stringify(rec));
  } catch {
    /* kept in memory only: a convenience, never a reason to fail */
  }
}

export function useWatchRecording(projectId: string, watch: WatchState) {
  const [rec, setRec] = useState<Recording>(() => load(projectId));
  // Which project the recording in `rec` belongs to, so that switching projects never writes one project's chats under another's name.
  const owner = useRef(projectId);

  // Order matters: this runs before the load below, while `owner` still names the old project, so the old recording is not saved
  // under the new project's key.
  useEffect(() => {
    if (owner.current === projectId) save(projectId, rec);
  }, [projectId, rec]);
  useEffect(() => {
    if (owner.current === projectId) return;
    owner.current = projectId;
    setRec(load(projectId));
  }, [projectId]);

  // Every change of what Watch live knows: take in whatever has finished. (A no-op, and no re-render, while nothing new has.)
  useEffect(() => {
    setRec((r) => take(r, watch));
  }, [watch]);

  const start = useCallback((want?: number) => setRec((r) => startRecording(r, want ?? r.want)), []);
  const stop = useCallback(() => setRec((r) => stopRecording(r)), []);
  const clear = useCallback(() => setRec((r) => clearRecording(r)), []);
  const setWant = useCallback((n: number) => setRec((r) => (r.on ? r : { ...r, want: clampWant(n) })), []);

  const summary = useMemo(() => summarise(rec), [rec]);
  return { recording: rec, summary, start, stop, clear, setWant };
}

export type WatchRecording = ReturnType<typeof useWatchRecording>;
