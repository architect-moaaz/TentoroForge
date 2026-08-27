/**
 * Mutation queue — Spec E Wave 1 runtime primitive.
 *
 * Wraps every workflow dispatch (or arbitrary async mutation) so the
 * user sees the intended state immediately and any server error
 * transparently rolls back + surfaces a toast that offers Undo.
 *
 * Design: intentionally NO dependency on the library package. The queue
 * publishes CustomEvents onto `window` (`forge:undo:push` /
 * `forge:undo:dismiss`) that the `<UndoManager>` component listens for.
 * Callers register an inverse mutation at submit time — the queue owns
 * pushing it onto the undo stack once the server confirms.
 */

import * as React from "react";

export type MutationStatus = "pending" | "confirmed" | "rolledback" | "failed";

export interface Mutation<T = unknown> {
  id: string;
  /** Human label shown in the toast ("Task moved", "Row deleted"). */
  label: string;
  /** Fires the server-side change. Resolved value is passed to `onConfirm`. */
  run: () => Promise<T>;
  /** Applied immediately for optimistic UI. Return the "next" state patch. */
  apply?: () => void;
  /** Reverse of `apply` — called on failure or when the user hits Undo. */
  rollback?: () => void;
  /**
   * Optional. If provided the queue publishes the undo toast on
   * success — clicking Undo calls the returned inverse mutation.
   */
  inverse?: (result: T) => Promise<void> | void;
  /** Fired after the server confirms. */
  onConfirm?: (result: T) => void;
  /** Fired after a rollback (either failure or Undo). */
  onRollback?: (err?: unknown) => void;
}

type Listener = (queue: readonly MutationEntry[]) => void;

interface MutationEntry {
  id: string;
  status: MutationStatus;
  label: string;
  startedAt: number;
}

let _seq = 0;
const nextId = () => `mut_${Date.now().toString(36)}_${(_seq++).toString(36)}`;

class MutationQueue {
  private entries: MutationEntry[] = [];
  private listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.entries);
    return () => {
      this.listeners.delete(listener);
    };
  }

  snapshot(): readonly MutationEntry[] {
    return this.entries;
  }

  private emit() {
    for (const l of this.listeners) l(this.entries);
  }

  private set(id: string, patch: Partial<MutationEntry>) {
    this.entries = this.entries.map((e) => (e.id === id ? { ...e, ...patch } : e));
    this.emit();
  }

  async submit<T>(m: Mutation<T>): Promise<T> {
    const id = m.id || nextId();
    const entry: MutationEntry = {
      id,
      status: "pending",
      label: m.label,
      startedAt: Date.now(),
    };
    this.entries = [...this.entries, entry];
    this.emit();

    try {
      m.apply?.();
    } catch (err) {
      // Optimistic apply should not throw; log and continue.
      // eslint-disable-next-line no-console
      console.warn("[mutation-queue] optimistic apply threw", err);
    }

    try {
      const result = await m.run();
      this.set(id, { status: "confirmed" });
      m.onConfirm?.(result);

      // Publish an undo toast if the mutation is undoable.
      if (m.inverse && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("forge:undo:push", {
            detail: {
              id: `undo_${id}`,
              label: m.label,
              undo: async () => {
                try {
                  await m.inverse!(result);
                  m.rollback?.();
                  m.onRollback?.();
                } catch (err) {
                  // eslint-disable-next-line no-console
                  console.error("[mutation-queue] undo failed", err);
                }
              },
            },
          }),
        );
      }
      return result;
    } catch (err) {
      try {
        m.rollback?.();
      } catch (rbErr) {
        // eslint-disable-next-line no-console
        console.warn("[mutation-queue] rollback threw", rbErr);
      }
      this.set(id, { status: "failed" });
      m.onRollback?.(err);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("forge:undo:push", {
            detail: {
              id: `err_${id}`,
              label: `${m.label} failed — reverted`,
              undo: () => {
                /* nothing to undo — already rolled back */
              },
            },
          }),
        );
      }
      throw err;
    }
  }

  /** Clears entries in a terminal state so the snapshot stays bounded. */
  reap(): void {
    this.entries = this.entries.filter((e) => e.status === "pending");
    this.emit();
  }
}

// Module-level singleton so the queue survives re-renders.
export const mutationQueue = new MutationQueue();

/**
 * React hook exposing the queue snapshot. Consumers rarely need the
 * queue directly — the toast lives in `<UndoManager>` — but pages that
 * want a "3 pending changes" chip can subscribe.
 */
export function useMutationQueue(): readonly MutationEntry[] {
  const [snapshot, setSnapshot] = React.useState<readonly MutationEntry[]>(
    mutationQueue.snapshot(),
  );
  React.useEffect(() => {
    return mutationQueue.subscribe(setSnapshot);
  }, []);
  return snapshot;
}

/** Convenience wrapper: submit a mutation from anywhere. */
export function submitMutation<T>(m: Mutation<T>): Promise<T> {
  return mutationQueue.submit(m);
}
