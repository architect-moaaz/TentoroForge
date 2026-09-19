"use client";
/**
 * Pages and the menu (EDIT-002): make a page, rename it, choose who may open
 * it, remove it knowing what goes with it, and arrange the app's menu — the
 * same menu the app's rail and public header are built from.
 */
import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, FileText, GripVertical, MoreHorizontal, Plus, Search, Star, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { editorApi, failureOf, type NavItemSpec } from "./api";
import { useEditorStore } from "./store";
import type { NavItem, PageListItem } from "./types";

export function routeFromName(name: string): string {
  const s = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return "/" + (s || "page");
}

export function PagesPanel() {
  const projectId = useEditorStore((s) => s.projectId)!;
  const pages = useEditorStore((s) => s.pages);
  const navigation = useEditorStore((s) => s.navigation);
  const entryPage = useEditorStore((s) => s.entryPage);
  const pageId = useEditorStore((s) => s.pageId);
  const openPage = useEditorStore((s) => s.openPage);
  const loadPages = useEditorStore((s) => s.loadPages);
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<PageListItem | null>(null);
  const [removing, setRemoving] = useState<PageListItem | null>(null);
  const shown = pages.filter((p) => !q || `${p.name} ${p.route} ${p.purpose}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="p-2">
      <div className="mb-2 flex gap-1">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input className="h-8 pl-7 text-xs" placeholder="Find a page" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a page" />
        </div>
        <Button size="sm" className="h-8 text-xs" onClick={() => setCreating(true)}><Plus className="h-3.5 w-3.5" /> New page</Button>
      </div>
      {!pages.length && <p className="p-2 text-xs text-muted-foreground">No pages yet — make one with “New page”.</p>}
      {shown.map((p) => (
        <div key={p.id} className={cn("group flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted", pageId === p.id && "bg-primary/10")}>
          <button type="button" onClick={() => void openPage(p.id)} title={p.purpose} className="flex min-w-0 flex-1 items-start gap-2 text-left">
            <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1 text-xs font-medium">
                <span className="truncate">{p.name}</span>
                {entryPage === p.id && <Star className="h-3 w-3 fill-amber-400 text-amber-400" aria-label="The first page people see" />}
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">{p.route}{p.access === "public" ? " · everyone" : ""}</span>
            </span>
          </button>
          {!p.coded && <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground" title="Laid out automatically; ask Smith to design it">auto</span>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className="rounded p-1 text-muted-foreground opacity-0 hover:bg-background group-hover:opacity-100 focus:opacity-100" aria-label={`More for ${p.name}`}><MoreHorizontal className="h-3.5 w-3.5" /></button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setRenaming(p)}>Rename or change address…</DropdownMenuItem>
              <DropdownMenuItem disabled={entryPage === p.id || p.route.includes("[")} onClick={() => void editorApi.setNavigation(projectId, { initialRoute: p.route }).then(() => loadPages()).catch((err) => toast.error("Couldn't change the first page.", { description: failureOf(err).message }))}>Make it the first page</DropdownMenuItem>
              <DropdownMenuItem disabled={!!navigation?.tree.some((n) => n.page === p.id) || p.route.includes("[")} onClick={() => void editorApi.setNavigation(projectId, { tree: [...(navigation?.tree ?? []).map(toSpec), { label: p.name, page: p.id }] }).then(() => loadPages()).catch((err) => toast.error("Couldn't add it to the menu.", { description: failureOf(err).message }))}>Add to the menu</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => setRemoving(p)}>Remove this page…</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ))}
      <MenuEditor />
      {creating && <NewPageDialog onClose={() => setCreating(false)} />}
      {renaming && <RenameDialog page={renaming} onClose={() => setRenaming(null)} />}
      {removing && <RemoveDialog page={removing} onClose={() => setRemoving(null)} />}
    </div>
  );
}

function toSpec(n: NavItem): NavItemSpec {
  return { label: n.label, page: n.page ?? null, icon: n.icon ?? null, children: (n.children ?? []).map(toSpec) };
}

function NewPageDialog({ onClose }: { onClose: () => void }) {
  const projectId = useEditorStore((s) => s.projectId)!;
  const loadPages = useEditorStore((s) => s.loadPages);
  const openPage = useEditorStore((s) => s.openPage);
  const pages = useEditorStore((s) => s.pages);
  const [name, setName] = useState("");
  const [route, setRoute] = useState("");
  const [routeTouched, setRouteTouched] = useState(false);
  const [menu, setMenu] = useState(true);
  const [everyone, setEveryone] = useState(pages.some((p) => p.access === "public"));
  const [busy, setBusy] = useState(false);
  const addr = routeTouched ? route : routeFromName(name);
  const taken = pages.find((p) => p.route.replace(/\/$/, "") === addr.replace(/\/$/, ""));
  const create = async () => {
    setBusy(true);
    try {
      const out = await editorApi.createPage(projectId, { name: name.trim(), route: addr, menu, access: everyone ? "public" : "authenticated" });
      await loadPages();
      await openPage(out.page.id);
      toast.success(`“${out.page.name}” is ready — add things to it from the Add panel.`);
      onClose();
    } catch (err) {
      toast.error("Couldn't make the page.", { description: failureOf(err).message, duration: 8000 });
    } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>New page</DialogTitle><DialogDescription>A blank page you can fill from the Add panel. It becomes part of the application right away.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div><Label className="mb-1 block text-xs">Name</Label><Input autoFocus value={name} placeholder="e.g. Team members" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && name.trim() && !taken) void create(); }} /></div>
          <div>
            <Label className="mb-1 block text-xs">Address</Label>
            <Input value={addr} onChange={(e) => { setRouteTouched(true); setRoute(e.target.value.startsWith("/") ? e.target.value : "/" + e.target.value); }} />
            <p className="mt-1 text-[11px] text-muted-foreground">{taken ? <span className="text-destructive">“{taken.name}” already uses this address.</span> : "What people see in the browser's address bar. Lowercase words joined by dashes."}</p>
          </div>
          <label className="flex items-center justify-between text-sm"><span>Show it in the menu</span><Switch checked={menu} onCheckedChange={setMenu} /></label>
          <label className="flex items-center justify-between text-sm"><span>Anyone can open it (no sign-in)</span><Switch checked={everyone} onCheckedChange={setEveryone} /></label>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" disabled={busy || !name.trim() || !!taken} onClick={() => void create()}>{busy ? "Making…" : "Make the page"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RenameDialog({ page, onClose }: { page: PageListItem; onClose: () => void }) {
  const projectId = useEditorStore((s) => s.projectId)!;
  const loadPages = useEditorStore((s) => s.loadPages);
  const reload = useEditorStore((s) => s.reload);
  const [name, setName] = useState(page.name);
  const [route, setRoute] = useState(page.route);
  const [everyone, setEveryone] = useState(page.access === "public");
  const [busy, setBusy] = useState(false);
  const record = page.route.includes("[");
  const save = async () => {
    setBusy(true);
    try {
      const spec: { name?: string; route?: string; access?: "public" | "authenticated" } = {};
      if (name.trim() !== page.name) spec.name = name.trim();
      if (!record && route !== page.route) spec.route = route;
      if ((everyone ? "public" : "authenticated") !== page.access) spec.access = everyone ? "public" : "authenticated";
      const out = await editorApi.updatePage(projectId, page.id, spec);
      await loadPages();
      await reload();
      if (out.renamed) toast.info(`Links to this page were updated to its new name.`);
      onClose();
    } catch (err) {
      toast.error("Couldn't change the page.", { description: failureOf(err).message, duration: 8000 });
    } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Change “{page.name}”</DialogTitle><DialogDescription>Its name in the menu and in links, its address, and who may open it.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div><Label className="mb-1 block text-xs">Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label className="mb-1 block text-xs">Address</Label><Input value={route} disabled={record} onChange={(e) => setRoute(e.target.value)} />
            {record && <p className="mt-1 text-[11px] text-muted-foreground">This page shows one record; its address carries the record's id.</p>}</div>
          <label className="flex items-center justify-between text-sm"><span>Anyone can open it (no sign-in)</span><Switch checked={everyone} onCheckedChange={setEveryone} /></label>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" disabled={busy || !name.trim()} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RemoveDialog({ page, onClose }: { page: PageListItem; onClose: () => void }) {
  const projectId = useEditorStore((s) => s.projectId)!;
  const loadPages = useEditorStore((s) => s.loadPages);
  const openPage = useEditorStore((s) => s.openPage);
  const pageId = useEditorStore((s) => s.pageId);
  const [info, setInfo] = useState<{ refusal: string | null; links?: unknown[]; menu?: unknown[]; widgets?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void editorApi.pageConsequences(projectId, page.id).then(setInfo).catch(() => setInfo({ refusal: null })); }, [projectId, page.id]);
  const remove = async () => {
    setBusy(true);
    try {
      const out = await editorApi.deletePage(projectId, page.id);
      await loadPages();
      if (pageId === page.id) { const next = useEditorStore.getState().pages.find((p) => p.coded); if (next) await openPage(next.id); }
      toast.success(`“${page.name}” was removed.`, { description: out.links.length ? `${out.links.length} link${out.links.length === 1 ? "" : "s"} to it came off other pages.` : undefined });
      onClose();
    } catch (err) {
      toast.error("Couldn't remove the page.", { description: failureOf(err).message, duration: 8000 });
    } finally { setBusy(false); }
  };
  const links = (info?.links as unknown[] | undefined)?.length ?? 0;
  const menu = (info?.menu as unknown[] | undefined)?.length ?? 0;
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Remove “{page.name}”?</DialogTitle>
          <DialogDescription>
            {!info ? "Checking what this would change…" : info.refusal ? info.refusal
              : `The page leaves the application. ${links ? `${links} link${links === 1 ? "" : "s"} on other pages open it and will be taken off. ` : "Nothing links to it. "}${menu ? "It comes off the menu. " : ""}You can bring it back from the project's history.`}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Keep it</Button>
          <Button size="sm" variant="destructive" disabled={busy || !info || !!info.refusal} onClick={() => void remove()}><Trash2 className="h-3.5 w-3.5" /> {busy ? "Removing…" : "Remove"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The app's menu: the order people see, each entry's words, and what is in it. */
function MenuEditor() {
  const projectId = useEditorStore((s) => s.projectId)!;
  const navigation = useEditorStore((s) => s.navigation);
  const pages = useEditorStore((s) => s.pages);
  const loadPages = useEditorStore((s) => s.loadPages);
  const [items, setItems] = useState<NavItem[]>(navigation?.tree ?? []);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<number | null>(null);
  useEffect(() => { setItems(navigation?.tree ?? []); setDirty(false); }, [navigation]);
  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= items.length) return;
    const next = [...items]; const [it] = next.splice(from, 1); next.splice(to, 0, it); setItems(next); setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    try { await editorApi.setNavigation(projectId, { tree: items.map(toSpec) }); await loadPages(); toast.success("Menu saved."); }
    catch (err) { toast.error("Couldn't save the menu.", { description: failureOf(err).message, duration: 8000 }); }
    finally { setBusy(false); }
  };
  if (!navigation) return null;
  const nameOf = (id?: string | null) => pages.find((p) => p.id === id)?.name;
  return (
    <div className="mt-4 border-t border-border pt-3">
      <div className="mb-1 flex items-center px-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Menu</span>
        <span className="ml-1 text-[10px] text-muted-foreground">· {navigation.style === "sidebar" ? "side rail" : navigation.style === "topbar" ? "top bar" : "rail and bar"}</span>
        <div className="flex-1" />
        {dirty && <Button size="xs" onClick={() => void save()} disabled={busy}>{busy ? "Saving…" : "Save menu"}</Button>}
      </div>
      {!items.length && <p className="px-1 text-[11px] text-muted-foreground">Nothing in the menu yet — use a page's … menu to add it.</p>}
      <ul>
        {items.map((it, i) => (
          <li key={`${it.page ?? it.label}-${i}`} draggable onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (drag != null) move(drag, i); setDrag(null); }}
            className="group flex items-center gap-1 rounded-md px-1 py-1 text-xs hover:bg-muted">
            <GripVertical className="h-3 w-3 shrink-0 text-muted-foreground/50" />
            <input className="min-w-0 flex-1 bg-transparent px-1 text-xs outline-none focus:bg-background" value={it.label} aria-label="Menu label"
              onChange={(e) => { const next = [...items]; next[i] = { ...it, label: e.target.value }; setItems(next); setDirty(true); }} />
            <span className="truncate text-[10px] text-muted-foreground">{nameOf(it.page) ?? (it.children?.length ? `${it.children.length} inside` : "")}</span>
            <button type="button" className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-background group-hover:opacity-100" aria-label="Move up" onClick={() => move(i, i - 1)}><ChevronUp className="h-3 w-3" /></button>
            <button type="button" className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-background group-hover:opacity-100" aria-label="Move down" onClick={() => move(i, i + 1)}><ChevronDown className="h-3 w-3" /></button>
            <button type="button" className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-background group-hover:opacity-100" aria-label="Take off the menu" onClick={() => { setItems(items.filter((_, j) => j !== i)); setDirty(true); }}><X className="h-3 w-3" /></button>
          </li>
        ))}
      </ul>
      <p className="mt-1 px-1 text-[10px] text-muted-foreground">Drag to reorder. The first page (★) is where the app opens.</p>
    </div>
  );
}
