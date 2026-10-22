"use client";
/**
 * Changing a part of a phone screen by hand: its words, a copy of it, taking it away.
 *
 * The part is the one the person clicked in the picture. A change is saved into the plan (the Blueprint) at once, and the picture is
 * drawn again after it. A change that would break the screen is refused with the reason; a change made on an older version of the
 * screen is refused and the screen reloaded. What is not here yet: looks, moving and adding parts.
 */
import { useCallback, useEffect, useState } from "react";
import { Copy, Loader2, Trash2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { editorApi, failureOf } from "./api";
import { fieldsOf, findPart, isScreenRoot, opFor, screenOf, type Field, type Source } from "./phoneParts";
import type { Op, PhoneScreen } from "./types";

export function PartEditor({ projectId, source }: { projectId: string; source: Source }) {
  const where = screenOf(source.file);
  const pageId = where?.page ?? null;
  const [screen, setScreen] = useState<PhoneScreen | null>(null);
  const [loadError, setLoadError] = useState("");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string[] } | null>(null);
  const [undo, setUndo] = useState<{ revision: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    if (!pageId) return;
    setLoadError("");
    try { setScreen(await editorApi.phoneScreen(projectId, pageId)); }
    catch (err) { setScreen(null); setLoadError(failureOf(err).message); }
  }, [projectId, pageId]);

  useEffect(() => { setUndo(null); }, [pageId]);
  // Each pick reads the screen again: a copy kept from the last pick may be older than the screen is.
  useEffect(() => {
    setScreen(null);
    setTyped({});
    setMessage(null);
    setConfirmDelete(false);
    void load();
  }, [load, source.file, source.line, source.component]);

  if (!pageId) {
    return <p className="text-xs text-muted-foreground">This part is drawn by the app itself, not by a screen written for it. Ask Smith to change it.</p>;
  }
  if (loadError) return <p className="text-xs text-red-600">{loadError}</p>;
  if (!screen) return <p className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading the screen…</p>;

  const part = findPart(screen.model.nodes, source);
  if (!part) {
    return <p className="text-xs text-muted-foreground">This part could not be found in the screen's code (it may have just changed). Ask Smith to change it.</p>;
  }
  const fields = fieldsOf(part, screen.words);
  const root = isScreenRoot(part);

  async function run(ops: Op[], label: string, done: string) {
    if (!screen) return;
    setBusy(true);
    setMessage(null);
    try {
      const out = await editorApi.applyPhoneScreen(projectId, screen.page.id, screen.revision, ops, label);
      setScreen({ ...screen, revision: out.revision, model: out.model });
      setUndo(out.history?.parent ? { revision: out.history.parent } : null);
      setTyped({});
      setConfirmDelete(false);
      setMessage({ tone: "ok", text: [out.unchanged ? "Nothing was different." : done] });
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") void load();
      setMessage({ tone: "bad", text: f.findings?.length ? f.findings.map((x) => x.plain) : [f.message] });
    } finally {
      setBusy(false);
    }
  }

  async function takeBack() {
    if (!screen || !undo) return;
    setBusy(true);
    setMessage(null);
    try {
      const out = await editorApi.restorePhoneScreen(projectId, screen.page.id, undo.revision, screen.revision);
      setScreen({ ...screen, revision: out.revision, model: out.model });
      setUndo(null);
      setMessage({ tone: "ok", text: ["Taken back."] });
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") void load();
      setMessage({ tone: "bad", text: [f.message] });
    } finally {
      setBusy(false);
    }
  }

  const key = (f: Field) => `${f.kind}:${f.name}`;
  const value = (f: Field) => typed[key(f)] ?? f.value;
  const changed = fields.filter((f) => typed[key(f)] !== undefined && typed[key(f)] !== f.value);

  return (
    <div className="space-y-2 rounded-md border p-2 text-xs" data-testid="part-editor">
      <p className="font-medium">{part.type}</p>
      {part.repeat ? (
        <p className="text-[11px] text-muted-foreground">This part is drawn once for each row, so a change here changes every row.</p>
      ) : null}

      {fields.length === 0 && (
        <p className="text-muted-foreground">Nothing here is plain words to type over{part.text ? " (its words come from data)" : ""}. Ask Smith to change it.</p>
      )}
      {fields.map((f) => (
        <div key={key(f)}>
          <label className="text-[11px] text-muted-foreground" htmlFor={`part-${key(f)}`}>{f.label}</label>
          <input
            id={`part-${key(f)}`}
            value={value(f)}
            disabled={busy}
            onChange={(e) => setTyped((t) => ({ ...t, [key(f)]: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && changed.length) { e.preventDefault(); void run(changed.map((c) => opFor(part, c, value(c))), "Change words", "Saved."); }
            }}
            className="mt-0.5 w-full rounded-md border bg-background px-2 py-1 text-sm"
          />
        </div>
      ))}
      {changed.length > 0 && (
        <Button size="sm" className="h-7 w-full text-xs" disabled={busy}
          onClick={() => void run(changed.map((c) => opFor(part, c, value(c))), "Change words", "Saved.")}>
          {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null} Save words
        </Button>
      )}

      {!root && (
        <div className="flex gap-1">
          <Button variant="outline" size="sm" className="h-7 flex-1 text-xs" disabled={busy}
            onClick={() => void run([{ op: "duplicate", id: part.id }], `Copy ${part.type}`, "Copied.")}>
            <Copy className="mr-1 h-3 w-3" /> Copy
          </Button>
          {confirmDelete ? (
            <>
              <Button variant="destructive" size="sm" className="h-7 flex-1 text-xs" disabled={busy}
                onClick={() => void run([{ op: "remove", ids: [part.id] }], `Delete ${part.type}`, "Deleted.")}>Delete it</Button>
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setConfirmDelete(false)}>Keep</Button>
            </>
          ) : (
            <Button variant="outline" size="sm" className="h-7 flex-1 text-xs" disabled={busy} onClick={() => setConfirmDelete(true)}>
              <Trash2 className="mr-1 h-3 w-3" /> Delete
            </Button>
          )}
        </div>
      )}

      {undo && (
        <Button variant="ghost" size="sm" className="h-7 w-full text-xs" disabled={busy} onClick={() => void takeBack()}>
          <Undo2 className="mr-1 h-3 w-3" /> Take back the last change
        </Button>
      )}

      {message && (
        <div role="status" className={message.tone === "ok" ? "text-emerald-700" : "text-red-600"}>
          {message.text.map((t, i) => <p key={i}>{t}</p>)}
        </div>
      )}
    </div>
  );
}

export default PartEditor;
