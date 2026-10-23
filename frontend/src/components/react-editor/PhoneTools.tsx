"use client";
/**
 * The tools for the phone screen on show, laid out as the website side lays them out: Add (the ready parts) and Layers (the
 * screen's parts as a list, to put them in another order by dragging) in the left panel beside Pages, and Change (the part that
 * was picked) on the right beside the picture.
 *
 * They all read and change the same screen, one version at a time: the provider holds the one session, and what was picked in
 * the picture or in Layers, so a change made in one panel is the screen the next one is made on.
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Loader2, Search, Undo2 } from "lucide-react";
import { create } from "zustand";

import { cn } from "@/lib/utils";

import { PartEditor } from "./PartEditor";
import { PART_DRAG_TYPE, usePhonePick } from "./phonePick";
import {
  GUIDED_PARTS, addOps, dropOp, dropPlace, findPart, kitNameOf, newPartAfterAdd, outlineOf, placeFor, resolveDrop, searchPalette,
  sourceOfPart, zoneAt, type Place, type Source, type Zone,
} from "./phoneParts";
import { GuidedDialog } from "./PhoneGuides";
import type { GuideKind, GuideSpec, PalettePart, PhoneKit, PhoneModel, PhonePart } from "./types";
import { usePhoneKit, usePhoneScreen, type PhoneSession } from "./usePhoneScreen";

export { usePhonePick, PART_DRAG_TYPE };

const Tools = createContext<{ session: PhoneSession; kit: PhoneKit | null; source: Source | null; pageId: string | null } | null>(null);

function useTools() {
  const t = useContext(Tools);
  if (!t) throw new Error("The phone tools are used inside PhoneToolsProvider.");
  return t;
}

export function PhoneToolsProvider({ projectId, children }: { projectId: string; children: ReactNode }) {
  const { source, pageId, listed } = usePhonePick();
  const chosen = listed ?? source;
  const kit = usePhoneKit(projectId);
  const session = usePhoneScreen(projectId, pageId, chosen ? `${chosen.file}:${chosen.line}:${chosen.component}` : "");
  const value = useMemo(() => ({ session, kit, source: chosen, pageId }), [session, kit, chosen, pageId]);
  const guide = usePhonePick((s) => s.guide);
  const set = usePhonePick((s) => s.set);
  const screen = session.screen;
  const add = async (spec: GuideSpec) => {
    if (!guide || !screen) return false;
    const model = await session.guided(spec, `Added ${GUIDE_WORDS[guide.kind]} ${guide.place.says}.`);
    if (!model) return false;
    selectNew(set, pageId, screen.model.nodes, guide.place, model);
    set({ guide: null });
    return true;
  };
  return (
    <Tools.Provider value={value}>
      {children}
      {guide && screen && (
        <GuidedDialog guide={guide} refs={screen.guides} nodes={screen.model.nodes} busy={session.busy}
          onClose={() => set({ guide: null })} onAdd={add} />
      )}
    </Tools.Provider>
  );
}

const GUIDE_WORDS: Record<GuideKind, string> = { form: "a form", button: "a button", list: "a list" };

/** Open the questions for a guided part that is to go in `place`. */
export function askAboutPart(kind: GuideKind, place: Place) {
  usePhonePick.getState().set({ guide: { kind, place } });
}

/** After a part is added, make it the picked part: the Change panel shows it, and its words are ready to be typed over. */
function selectNew(set: (patch: { listed: Source; fresh: string }) => void, pageId: string | null, before: Record<string, PhonePart>, place: Place,
                   after: PhoneModel) {
  const added = newPartAfterAdd(before, place, after.nodes);
  if (added && pageId) set({ listed: sourceOfPart(pageId, added), fresh: added.id });
}

function useSelectNew() {
  const tools = useContext(Tools);
  const set = usePhonePick((s) => s.set);
  return (before: Record<string, PhonePart>, place: Place, after: PhoneModel) => selectNew(set, tools?.pageId ?? null, before, place, after);
}

/**
 * Dropping the part being dragged: on a part of the screen (`onPart`, from Layers), or on what the picture says was under the
 * pointer (`onSource`, with how far down it: 0 at its top, 1 at its bottom). Both end in the same addition as a click on the part.
 */
export function usePhoneDrop() {
  const tools = useContext(Tools);
  const dragging = usePhonePick((s) => s.dragging);
  const set = usePhonePick((s) => s.set);
  const screen = tools?.session.screen ?? null;
  const kit = tools?.kit ?? null;
  const run = tools?.session.run;
  const containers = kit?.containers ?? [];
  const select = useSelectNew();
  const add = async (part: PalettePart, place: ReturnType<typeof dropPlace>) => {
    if (!place || !run || !screen) return false;
    if (part.guided) { askAboutPart(part.guided, place); return true; }
    const model = await run(addOps(part, place), `Add ${part.label.toLowerCase()}`, `Added ${part.label.toLowerCase()} ${place.says}.`);
    if (model) select(screen.model.nodes, place, model);
    return !!model;
  };
  return {
    dragging,
    canHold: (part: PhonePart) => !!screen && containers.includes(kitNameOf(part, screen.model.imports) ?? ""),
    onPart: (target: PhonePart, zone: Zone) =>
      screen && dragging ? add(dragging, dropPlace(screen.model.nodes, screen.model.imports, containers, target, zone)) : Promise.resolve(false),
    /** The picture says a part was dropped on what it drew. Resolves to why it could not be added, or null when it was (or when the
     *  change itself was refused, which says its own reason). */
    onSource: async (source: Source | null, rel: number, partId?: string): Promise<string | null> => {
      const decided = resolveDrop({ nodes: screen?.model.nodes ?? null, imports: screen?.model.imports ?? {}, kit, dragging, partId, source, rel });
      if ("why" in decided) return decided.why;
      await add(decided.part, decided.place);
      return null;
    },
    end: () => set({ dragging: null }),
  };
}

/** What the last change said, and the way back. Shown under whichever panel the change was made from. */
function SaidBar() {
  const { session: { said, busy, canTakeBack, takeBack } } = useTools();
  return (
    <>
      {canTakeBack && (
        <button type="button" disabled={busy} onClick={() => void takeBack()}
          className="mt-2 flex w-full items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:text-foreground">
          <Undo2 className="h-3 w-3" /> Take back the last change
        </button>
      )}
      {said && (
        <div role="status" className={cn("mt-2 text-xs", said.tone === "ok" ? "text-emerald-700" : "text-red-600")}>
          {said.text.map((t, i) => <p key={i}>{t}</p>)}
        </div>
      )}
    </>
  );
}

/** Change: the part that was picked. On the right, beside the picture. */
export function ChangePanel() {
  const { session, kit, source } = useTools();
  return (
    <div data-testid="phone-change">
      {source
        ? <PartEditor session={session} kit={kit} source={source} />
        : <p className="text-xs text-muted-foreground">Choose <strong>Select to change</strong>, then click a part of the screen. Or pick one in Layers.</p>}
      <SaidBar />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add
// ---------------------------------------------------------------------------

export function AddPanel() {
  const { session, kit, source } = useTools();
  const { screen, busy, run } = session;
  const [text, setText] = useState("");
  const setDragging = (p: PalettePart | null) => usePhonePick.getState().set({ dragging: p });
  const palette = [...GUIDED_PARTS, ...(kit?.palette ?? [])];
  const selected = useMemo(() => (screen && source ? findPart(screen.model.nodes, source) : null), [screen, source]);
  const place = useMemo(
    () => (screen ? placeFor(screen.model.nodes, screen.model.imports, kit?.containers ?? [], selected) : null),
    [screen, kit, selected]);
  const shown = searchPalette(palette, text);
  const groups = [...new Set(shown.map((p) => p.category))];

  if (!kit) return <p className="flex items-center gap-1 p-2 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading the parts…</p>;
  const select = useSelectNew();
  const add = (part: PalettePart) => {
    if (!place || !screen) return;
    if (part.guided) { askAboutPart(part.guided, place); return; }
    void run(addOps(part, place), `Add ${part.label.toLowerCase()}`, `Added ${part.label.toLowerCase()}.`)
      .then((model) => { if (model) select(screen.model.nodes, place, model); });
  };

  return (
    <div className="space-y-2 p-2" data-testid="phone-add">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1.5 h-3.5 w-3.5 text-muted-foreground" />
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a part" aria-label="Find a part"
          className="w-full rounded-md border bg-background py-1 pl-7 pr-2 text-xs" />
      </div>
      <p className="text-[11px] text-muted-foreground">
        {place ? <>Click a part to add it {place.says}, or drag it onto the screen or into Layers.</> : "This screen has nowhere to add a part."}
      </p>
      {groups.map((group) => (
        <div key={group}>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{group}</p>
          <div className="grid grid-cols-2 gap-1">
            {shown.filter((p) => p.category === group).map((p) => (
              <button key={p.id} type="button" disabled={busy || !place} onClick={() => add(p)} title={`${p.description}. Click to add, or drag it onto the screen.`}
                draggable={!busy}
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = "copy";
                  e.dataTransfer.setData(PART_DRAG_TYPE, p.id);
                  e.dataTransfer.setData("text/plain", p.label);
                  setDragging(p);
                }}
                // A browser says "drag ended" before the picture's drop message arrives, so the part is kept a moment longer.
                onDragEnd={() => window.setTimeout(() => { if (usePhonePick.getState().dragging?.id === p.id) setDragging(null); }, 4000)}
                className="cursor-grab rounded-md border px-2 py-1.5 text-left text-xs hover:bg-muted disabled:opacity-50">
                <span className="block font-medium">{p.label}</span>
                {p.drawnOnly && <span className="block text-[10px] text-muted-foreground">drawn only</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
      {shown.length === 0 && <p className="text-xs text-muted-foreground">No part matches “{text}”.</p>}
      {palette.some((p) => p.drawnOnly) && (
        <p className="text-[11px] text-muted-foreground">
          “Drawn only” parts look right but a box can't be typed into and a button does nothing yet. Ask Smith to connect them to your data.
        </p>
      )}
      {!kit.ok && <p className="text-[11px] text-amber-700">{kit.error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

export function LayersPanel() {
  const { session, source, pageId } = useTools();
  const set = usePhonePick((s) => s.set);
  const onSelect = (s: Source) => set({ listed: s });
  const { screen, busy, run } = session;
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<{ id: string; where: Zone } | null>(null);
  const incoming = usePhoneDrop();
  const rows = useMemo(() => (screen ? outlineOf(screen.model.nodes) : []), [screen]);
  const selected = useMemo(() => (screen && source ? findPart(screen.model.nodes, source) : null), [screen, source]);
  if (!pageId) return <p className="p-2 text-xs text-muted-foreground">Open a screen in the picture to see its parts.</p>;
  if (!screen) return <p className="flex items-center gap-1 p-2 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading the screen…</p>;
  const nodes = screen.model.nodes;

  const drop = () => {
    const op = drag && over && over.where !== "inside" ? dropOp(nodes, drag, over.id, over.where) : null;
    setDrag(null);
    setOver(null);
    if (op) void run([op], "Move part", "Moved.");
  };

  return (
    <div className="p-2" data-testid="phone-outline">
      <p className="mb-1 text-[11px] text-muted-foreground">Drag a part up or down among the parts beside it. Click one to change it.</p>
      <ul className="space-y-0.5">
        {rows.map(({ part, depth }) => {
          const movable = part.parent != null && !part.slot;
          const target = drag ? dropOp(nodes, drag, part.id, "before") !== null || dropOp(nodes, drag, part.id, "after") !== null : false;
          return (
            <li key={part.id}
              draggable={movable && !busy}
              onDragStart={(e) => { incoming.end(); setDrag(part.id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", part.id); }}
              onDragEnd={() => { setDrag(null); setOver(null); }}
              onDragOver={(e) => {
                const box = e.currentTarget.getBoundingClientRect();
                const rel = (e.clientY - box.top) / Math.max(1, box.height);
                if (incoming.dragging) {                      // a ready part from Add: before, after, or inside the part under the pointer
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "copy";
                  setOver({ id: part.id, where: zoneAt(rel, incoming.canHold(part)) });
                  return;
                }
                if (!drag || !target) return;
                e.preventDefault();
                setOver({ id: part.id, where: rel < 0.5 ? "before" : "after" });
              }}
              onDragLeave={() => setOver((o) => (o?.id === part.id ? null : o))}
              onDrop={(e) => {
                e.preventDefault();
                if (incoming.dragging && over) {
                  const at = over;
                  setOver(null);
                  void incoming.onPart(part, at.where).finally(incoming.end);
                  return;
                }
                drop();
              }}
              className={cn(
                "rounded border border-transparent",
                over?.id === part.id && over.where === "before" && "border-t-primary",
                over?.id === part.id && over.where === "after" && "border-b-primary",
                over?.id === part.id && over.where === "inside" && "border-primary bg-primary/10",
                drag === part.id && "opacity-40")}>
              <button type="button" onClick={() => onSelect(sourceOfPart(pageId, part))}
                style={{ paddingLeft: 6 + depth * 12 }}
                className={cn("flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs hover:bg-muted",
                  selected?.id === part.id && "bg-muted font-medium", movable ? "cursor-grab" : "cursor-default")}>
                <span className="shrink-0">{part.type}</span>
                {part.slot ? <span className="shrink-0 text-[10px] text-muted-foreground">({part.slot})</span> : null}
                {part.text ? <span className="truncate text-muted-foreground">{part.text.trim().slice(0, 28)}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
