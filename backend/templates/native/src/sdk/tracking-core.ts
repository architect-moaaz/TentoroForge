// The app SDK (native) — live tracking, the part with no screen in it: how a driver's notes go out. PURE (no
// react-native import), so it runs under plain node in the template's tests, and so the phone and the web send
// by the same rules.
//
// THE RULES (the same as the web's `useShareLocation`):
//   - a new reading goes out at most every HOW_OFTEN_MS;
//   - a note that could not go out waits, up to MAX_QUEUE of them (a long outage keeps the latest);
//   - waiting notes are tried again every RETRY_MS, and the moment the phone says it is online;
//   - a driver who has not moved says "still here" every STILL_HERE_MS with the last known spot, so a quiet line is
//     never read as a lost driver;
//   - a refusal that retrying cannot mend (not your trip, the job is over) empties the queue and says why; a
//     sign-in that lapsed or a server in trouble keeps it.

export type Note = Record<string, unknown> & { at: number };

/** What sending one note answered: `status` 0 means no answer came (the network). */
export type PostResult = { status: number; error?: string };

export const HOW_OFTEN_MS = 4_000;
export const RETRY_MS = 5_000;
export const STILL_HERE_MS = 20_000;
export const MAX_QUEUE = 50;

export interface SenderDeps {
  post(note: Note): Promise<PostResult>;
  now(): number;
  /** One note reached the server. */
  onSent(): void;
  /** The sentence to show (null: all is well now). */
  onError(message: string | null): void;
}

export interface Sender {
  /** A new reading from the device. Returns whether it was taken (not too soon after the last). */
  reading(note: Note): boolean;
  /** Called on a timer every RETRY_MS: tries waiting notes again, or says "still here". */
  tick(): Promise<void>;
  /** The phone says it is online again. */
  online(): Promise<void>;
  waiting(): number;
}

export function createSender(deps: SenderDeps): Sender {
  let queue: Note[] = [];
  let flushing = false;
  let lastSent = 0;
  let lastNote: Note | null = null;

  async function flush(): Promise<void> {
    if (flushing) return;
    flushing = true;
    try {
      while (queue.length) {
        const res = await deps.post(queue[0]);
        if (res.status === 401) { deps.onError("Sign in to share your location."); return; }
        if (res.status === 403 || res.status === 404) { queue = []; deps.onError("This trip is not yours to share."); return; }
        if (res.status === 409) { queue = []; deps.onError(res.error || "This job is over."); return; }
        if (res.status === 0 || res.status >= 500) { deps.onError("Could not send your location — trying again."); return; }
        queue.shift();
        deps.onSent();
        deps.onError(null);
      }
    } finally {
      flushing = false;
    }
  }

  return {
    reading(note) {
      const at = deps.now();
      if (at - lastSent < HOW_OFTEN_MS) return false;
      lastSent = at;
      lastNote = note;
      queue.push(note);
      if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
      void flush();
      return true;
    },
    async tick() {
      if (queue.length) return flush();
      if (lastNote && deps.now() - lastSent > STILL_HERE_MS) {
        lastSent = deps.now();
        queue.push({ ...lastNote, at: lastSent });
        return flush();
      }
    },
    async online() {
      if (queue.length) return flush();
    },
    waiting: () => queue.length,
  };
}
