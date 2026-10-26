"use client";
/**
 * One phone screen opened for editing, and the changes made to it: what the Change, Add and Outline tabs share.
 *
 * Every change names the version of the screen it was made on and is saved into the plan at once; the screen read back is the
 * one the next change is made on. A change refused (it would break the screen, or the screen moved on) says why in a sentence.
 */
import { useCallback, useEffect, useState } from "react";

import { editorApi, failureOf } from "./api";
import type { GuideSpec, Op, PhoneKit, PhoneModel, PhoneScreen } from "./types";

export interface Said {
  tone: "ok" | "bad";
  text: string[];
}

export interface PhoneSession {
  screen: PhoneScreen | null;
  loadError: string;
  busy: boolean;
  said: Said | null;
  /** A change can be taken back: the version before the last one. */
  canTakeBack: boolean;
  /** Makes the change. Resolves to the screen as it is after it, or null when the change was refused (`said` says why). */
  run: (ops: Op[], label: string, done: string) => Promise<PhoneModel | null>;
  /** A guided part (form, button, list): the server builds it from the names in `spec`. Same result as `run`. */
  guided: (spec: GuideSpec, done: string) => Promise<PhoneModel | null>;
  takeBack: () => Promise<void>;
  reload: () => Promise<void>;
}

export function usePhoneScreen(projectId: string, pageId: string | null, refreshKey = ""): PhoneSession {
  const [screen, setScreen] = useState<PhoneScreen | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said | null>(null);
  const [back, setBack] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!pageId) return;
    setLoadError("");
    try { setScreen(await editorApi.phoneScreen(projectId, pageId)); }
    catch (err) { setLoadError(failureOf(err).message); }
  }, [projectId, pageId]);

  // Another screen is a new start; a new pick reads the same screen again, since the copy kept may be older than the screen is.
  useEffect(() => { setScreen(null); setBack(null); setSaid(null); }, [pageId]);
  useEffect(() => { void reload(); }, [reload, refreshKey]);

  const run = useCallback(async (ops: Op[], label: string, done: string) => {
    if (!screen) return null;
    setBusy(true);
    setSaid(null);
    try {
      const out = await editorApi.applyPhoneScreen(projectId, screen.page.id, screen.revision, ops, label);
      setScreen({ ...screen, revision: out.revision, model: out.model });
      setBack(out.history?.parent ?? null);
      setSaid({ tone: "ok", text: [out.unchanged ? "Nothing was different." : done] });
      return out.model;
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") void reload();
      setSaid({ tone: "bad", text: f.findings?.length ? f.findings.map((x) => x.plain) : [f.message] });
      return null;
    } finally {
      setBusy(false);
    }
  }, [projectId, screen, reload]);

  const guided = useCallback(async (spec: GuideSpec, done: string) => {
    if (!screen) return null;
    setBusy(true);
    setSaid(null);
    try {
      const out = await editorApi.addGuidedPhonePart(projectId, screen.page.id, screen.revision, spec);
      setScreen({ ...screen, revision: out.revision, model: out.model });
      setBack(out.history?.parent ?? null);
      setSaid({ tone: "ok", text: [done] });
      return out.model;
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") void reload();
      setSaid({ tone: "bad", text: f.findings?.length ? f.findings.map((x) => x.plain) : [f.message] });
      return null;
    } finally {
      setBusy(false);
    }
  }, [projectId, screen, reload]);

  const takeBack = useCallback(async () => {
    if (!screen || !back) return;
    setBusy(true);
    setSaid(null);
    try {
      const out = await editorApi.restorePhoneScreen(projectId, screen.page.id, back, screen.revision);
      setScreen({ ...screen, revision: out.revision, model: out.model });
      setBack(null);
      setSaid({ tone: "ok", text: ["Taken back."] });
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") void reload();
      setSaid({ tone: "bad", text: [f.message] });
    } finally {
      setBusy(false);
    }
  }, [projectId, screen, back, reload]);

  return { screen, loadError, busy, said, canTakeBack: back !== null, run, guided, takeBack, reload };
}

/** What the kit lets a person choose, and the parts that can be added. Read once; it only changes when the kit does. */
export function usePhoneKit(projectId: string): PhoneKit | null {
  const [kit, setKit] = useState<PhoneKit | null>(null);
  useEffect(() => {
    let alive = true;
    editorApi.phoneKit(projectId).then((k) => { if (alive) setKit(k); }).catch(() => { if (alive) setKit(null); });
    return () => { alive = false; };
  }, [projectId]);
  return kit;
}
