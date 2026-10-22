"use client";
/**
 * Changing the part of a phone screen that was picked: its words, its look (the kit's own pick lists), its place among its
 * brothers, a copy of it, taking it away.
 *
 * Every change is saved into the plan at once and the picture is drawn again after it. The look is only ever a word the kit
 * offers for that setting, so it cannot break the screen; a setting the screen's own code decides is shown, not changed.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Copy, Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  choiceOp, choicesOf, fieldsOf, findPart, isScreenRoot, opFor, screenOf, stepOp, valueLabel,
  type Choice, type Field, type Source,
} from "./phoneParts";
import { usePhonePick } from "./phonePick";
import type { PhoneKit } from "./types";
import type { PhoneSession } from "./usePhoneScreen";

export function PartEditor({ session, kit, source }: { session: PhoneSession; kit: PhoneKit | null; source: Source }) {
  const { screen, loadError, busy, run } = session;
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const identity = `${source.file}:${source.line}:${source.component}`;
  const [seen, setSeen] = useState(identity);
  if (seen !== identity) { setSeen(identity); setTyped({}); setConfirmDelete(false); }

  const part = useMemo(() => (screen ? findPart(screen.model.nodes, source) : null), [screen, source]);
  const fields = useMemo(() => (part && screen ? fieldsOf(part, screen.words) : []), [part, screen]);
  const choices = useMemo(() => (part && screen ? choicesOf(part, kit, screen.model.imports) : []), [part, screen, kit]);

  // A part that was just added takes the cursor in its words box, with the words selected: type to replace them.
  const fresh = usePhonePick((s) => s.fresh);
  const setPick = usePhonePick((s) => s.set);
  const firstWords = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (part && fresh === part.id) {
      firstWords.current?.focus();
      firstWords.current?.select();
      setPick({ fresh: null });
    }
  }, [part, fresh, setPick, fields.length]);

  if (!screenOf(source.file)) {
    return <p className="text-xs text-muted-foreground">This part is drawn by the app itself, not by a screen written for it. Ask Smith to change it.</p>;
  }
  if (loadError) return <p className="text-xs text-red-600">{loadError}</p>;
  if (!screen) return <p className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading the screen…</p>;
  if (!part) {
    return <p className="text-xs text-muted-foreground">This part could not be found in the screen's code (it may have just changed). Ask Smith to change it.</p>;
  }

  const root = isScreenRoot(part);
  const key = (f: Field) => `${f.kind}:${f.name}`;
  const value = (f: Field) => typed[key(f)] ?? f.value;
  const changed = fields.filter((f) => typed[key(f)] !== undefined && typed[key(f)] !== f.value);
  const up = stepOp(screen.model.nodes, part, -1);
  const down = stepOp(screen.model.nodes, part, 1);
  const saveWords = () => run(changed.map((c) => opFor(part, c, value(c))), "Change words", "Saved.").then((ok) => { if (ok) setTyped({}); });
  const choose = (c: Choice, v: string | boolean | null) =>
    run([choiceOp(part, c, v)], `Change ${c.label.toLowerCase()}`, "Saved.");

  return (
    <div className="space-y-2 rounded-md border p-2 text-xs" data-testid="part-editor">
      <p className="font-medium">{part.type}</p>
      {part.repeat ? (
        <p className="text-[11px] text-muted-foreground">This part is drawn once for each row, so a change here changes every row.</p>
      ) : null}

      {fields.map((f, at) => (
        <div key={key(f)}>
          <label className="text-[11px] text-muted-foreground" htmlFor={`part-${key(f)}`}>{f.label}</label>
          <input
            id={`part-${key(f)}`}
            ref={at === 0 ? firstWords : undefined}
            value={value(f)}
            disabled={busy}
            onChange={(e) => setTyped((t) => ({ ...t, [key(f)]: e.target.value }))}
            onKeyDown={(e) => { if (e.key === "Enter" && changed.length) { e.preventDefault(); void saveWords(); } }}
            className="mt-0.5 w-full rounded-md border bg-background px-2 py-1 text-sm"
          />
        </div>
      ))}
      {changed.length > 0 && (
        <Button size="sm" className="h-7 w-full text-xs" disabled={busy} onClick={() => void saveWords()}>
          {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null} Save words
        </Button>
      )}
      {fields.length === 0 && choices.length === 0 && (
        <p className="text-muted-foreground">Nothing here is plain words or a choice to change{part.text ? " (its words come from data)" : ""}. Ask Smith to change it.</p>
      )}

      {choices.length > 0 && (
        <div className="space-y-1.5" data-testid="part-look">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Look</p>
          {choices.map((c) => (
            <ChoiceRow key={c.name} choice={c} kit={kit} part={part.id} disabled={busy} onChoose={(v) => void choose(c, v)} />
          ))}
        </div>
      )}

      {!root && (
        <div className="flex gap-1">
          <Button variant="outline" size="sm" className="h-7 flex-1 text-xs" disabled={busy || !up}
            onClick={() => up && void run([up], `Move ${part.type} up`, "Moved up.")}>
            <ArrowUp className="mr-1 h-3 w-3" /> Up
          </Button>
          <Button variant="outline" size="sm" className="h-7 flex-1 text-xs" disabled={busy || !down}
            onClick={() => down && void run([down], `Move ${part.type} down`, "Moved down.")}>
            <ArrowDown className="mr-1 h-3 w-3" /> Down
          </Button>
        </div>
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
    </div>
  );
}

/** One setting: a pick list (or a box with suggestions when the list is long, like the icons) or a switch. */
function ChoiceRow({ choice, kit, part, disabled, onChoose }:
  { choice: Choice; kit: PhoneKit | null; part: string; disabled: boolean; onChoose: (v: string | boolean | null) => void }) {
  const id = `look-${part}-${choice.name}`;
  if (choice.fromCode) {
    return (
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground">{choice.label}</span>
        <span className="text-[11px] italic text-muted-foreground">decided by the screen's code</span>
      </div>
    );
  }
  if (choice.kind === "boolean") {
    return (
      <label className="flex items-center justify-between gap-2" htmlFor={id}>
        <span>{choice.label}</span>
        <input id={id} type="checkbox" checked={choice.current === true} disabled={disabled}
          onChange={(e) => onChoose(e.target.checked ? true : null)} />
      </label>
    );
  }
  const values = choice.list ? (kit?.lists[choice.list] ?? []) : choice.values;
  const current = typeof choice.current === "string" ? choice.current : "";
  if (choice.list) {
    return (
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id}>{choice.label}</label>
        <input id={id} list={`${id}-list`} defaultValue={current} disabled={disabled} placeholder="none" key={current}
          onChange={(e) => { if (values.includes(e.target.value)) onChoose(e.target.value); else if (e.target.value === "" && choice.optional && current) onChoose(null); }}
          className="w-28 rounded-md border bg-background px-1.5 py-0.5 text-xs" />
        <datalist id={`${id}-list`}>{values.map((v) => <option key={v} value={v} />)}</datalist>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-2">
      <label htmlFor={id}>{choice.label}</label>
      <select id={id} value={current} disabled={disabled} onChange={(e) => onChoose(e.target.value === "" ? null : e.target.value)}
        className="w-32 rounded-md border bg-background px-1 py-0.5 text-xs">
        {choice.optional || current === "" ? <option value="">{current === "" ? "Default" : "Back to default"}</option> : null}
        {values.map((v) => <option key={v} value={v}>{valueLabel(v)}</option>)}
      </select>
    </div>
  );
}

export default PartEditor;
