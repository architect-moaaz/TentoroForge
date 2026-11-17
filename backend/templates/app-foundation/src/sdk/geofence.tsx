"use client";

/**
 * Geofencing screens — zones on a map, drawn and tuned by people, watched live.
 *
 *   <GeofenceMap />                                   every zone, on the map (click one to select it)
 *   <GeofenceEditor onSaved={(id) => …} />            draw a circle or a polygon, name it, save it
 *   <GeofenceEditor zone={zone} />                    the same, to move or reshape one
 *   <GeofenceMonitor entity="Order" />                crossings as they happen, with the zone and who
 *   <GeofenceEventTimeline entity="Order" id={o.id} />  what one record did, in order, with a map of where
 *   <GeofenceSettings zone={zone} />                  how forgiving a zone is, who it watches, and what it does
 *
 * A crossing is where a phone SAYS it is. These screens say so: an action that moves money, finishes a job or marks someone
 * present is shown as waiting for a confirmation that is not GPS, and it does not run on a crossing alone.
 *
 * Who may change zones is the server's decision (FORGE_GEOFENCE_ROLES, default "admin"); a person who may not sees the zones
 * and is told so. Crossings are shown only for records the person may already open.
 */
import * as React from "react";
import { MapView, type MapPoint, type MapZone } from "./map";
import type { GeoPoint } from "./geo";
import { invalidShape, distanceM, type Shape } from "@/lib/geofence/engine";
import { isSensitive, type Rule } from "@/lib/geofence/rules";

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export type Zone = {
  id: string; name: string; shape: Shape; active: boolean;
  rules: Record<string, number | boolean>; assign: string[]; owner?: unknown;
};
export type Crossing = {
  id: string; type: string; geofenceId: string; zoneName?: string | null; entityType: string; entityId: string;
  lat: number; lng: number; occurredAt: number; detectedAt: number; metadata: Record<string, unknown>;
};

const say = (e: unknown) => (e instanceof Error ? e.message : String(e));
async function call<T = Record<string, unknown>>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "same-origin", headers: { "content-type": "application/json" }, ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body?.ok === false) throw new Error(body?.error || `The server answered ${res.status}.`);
  return body as T;
}

/** A zone as the map draws it. */
export function asMapZone(z: Zone, tone: MapZone["tone"] = "primary"): MapZone {
  const base = { id: z.id, label: z.name, tone, inactive: !z.active };
  return z.shape.type === "circle"
    ? { ...base, shape: "circle", center: z.shape.center, radiusM: z.shape.radiusM }
    : { ...base, shape: "polygon", ring: z.shape.ring };
}

/** The zones, loaded once and again on `reload()`. */
export function useZones() {
  const [zones, setZones] = React.useState<Zone[]>([]);
  const [canManage, setCanManage] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const reload = React.useCallback(async () => {
    try {
      const r = await call<{ zones: Zone[]; canManage: boolean }>("/api/geofence/zones");
      setZones(r.zones); setCanManage(r.canManage); setError(null);
    } catch (e) { setError(say(e)); } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { void reload(); }, [reload]);
  return { zones, canManage, loading, error, reload };
}

const TYPE_TEXT: Record<string, string> = {
  "geofence.entered": "entered", "geofence.exited": "left", "geofence.dwell": "stayed", "geofence.approaching": "is approaching",
};
const TYPE_TONE: Record<string, MapPoint["tone"]> = {
  "geofence.entered": "primary", "geofence.exited": "muted", "geofence.dwell": "accent", "geofence.approaching": "accent",
};
export function describe(c: Crossing): string {
  const dwell = c.type === "geofence.dwell" && typeof c.metadata.dwellMs === "number" ? ` (${Math.round(Number(c.metadata.dwellMs) / 60000)} min)` : "";
  return `${c.entityType} ${c.entityId.slice(0, 8)} ${TYPE_TEXT[c.type] ?? c.type} ${c.zoneName ?? "a zone"}${dwell}`;
}
const clock = (t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

// ------------------------------------------------------------------------------------------------ 1. the map

export function GeofenceMap({ zones, points, selected, onSelect, height = 360 }: {
  zones?: Zone[]; points?: MapPoint[]; selected?: string | null; onSelect?: (id: string) => void; height?: number | string;
}) {
  const own = useZones();
  const list = zones ?? own.zones;
  const drawn = React.useMemo(() => list.map((z) => asMapZone(z, z.id === selected ? "accent" : "primary")), [list, selected]);
  return (
    <div className="space-y-2">
      <MapView zones={drawn} points={points} onZoneClick={onSelect} height={height} />
      {!zones && own.error && <p className="text-sm text-destructive">{own.error}</p>}
      {!zones && !own.loading && !own.error && list.length === 0 && <p className="text-sm text-muted-foreground">No zones yet.</p>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ 2. the editor

export function GeofenceEditor({ zone, center, onSaved }: { zone?: Zone; center?: GeoPoint; onSaved?: (id: string) => void }) {
  const [name, setName] = React.useState(zone?.name ?? "");
  const [kind, setKind] = React.useState<"circle" | "polygon">(zone?.shape.type ?? "circle");
  const [centre, setCentre] = React.useState<GeoPoint | null>(zone?.shape.type === "circle" ? zone.shape.center : null);
  const [radius, setRadius] = React.useState(zone?.shape.type === "circle" ? zone.shape.radiusM : 200);
  const [ring, setRing] = React.useState<GeoPoint[]>(zone?.shape.type === "polygon" ? zone.shape.ring : []);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<{ ok: boolean; text: string } | null>(null);

  const shape: Shape | null = kind === "circle" ? (centre ? { type: "circle", center: centre, radiusM: radius } : null) : (ring.length ? { type: "polygon", ring } : null);
  const problem = shape ? invalidShape(shape) : kind === "circle" ? "Click the map to place the centre." : "Click the map to add corners.";
  const drawn: MapZone[] = shape && !problem
    ? [asMapZone({ id: "draft", name: name || "New zone", shape, active: true, rules: {}, assign: [] }, "accent")]
    : [];
  const points: MapPoint[] = kind === "polygon" ? ring.map((p, i) => ({ id: `c${i}`, lat: p.lat, lng: p.lng, label: `Corner ${i + 1}`, tone: "accent" as const })) : centre ? [{ id: "centre", ...centre, label: "Centre", tone: "accent" as const }] : [];

  const click = (at: GeoPoint) => {
    setMessage(null);
    if (kind === "circle") setCentre(at); else setRing((r) => [...r, at]);
  };
  const save = async () => {
    if (!shape || problem || !name.trim()) { setMessage({ ok: false, text: !name.trim() ? "Give the zone a name." : problem ?? "Draw the zone first." }); return; }
    setBusy(true);
    try {
      const r = zone
        ? await call(`/api/geofence/zones?id=${encodeURIComponent(zone.id)}`, { method: "PATCH", body: JSON.stringify({ name, shape }) })
        : await call<{ id: string }>("/api/geofence/zones", { method: "POST", body: JSON.stringify({ name, shape }) });
      setMessage({ ok: true, text: zone ? "Saved." : "Zone added." });
      onSaved?.(zone?.id ?? (r as { id: string }).id);
      if (!zone) { setName(""); setCentre(null); setRing([]); }
    } catch (e) { setMessage({ ok: false, text: say(e) }); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">Name
          <input className="rounded-md border bg-background px-3 py-2" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Restaurant pick-up" />
        </label>
        <div className="flex overflow-hidden rounded-md border text-sm" role="group" aria-label="Shape">
          {(["circle", "polygon"] as const).map((k) => (
            <button key={k} type="button" className={"px-3 py-2 " + (kind === k ? "bg-primary text-primary-foreground" : "bg-background")} onClick={() => { setKind(k); setMessage(null); }}>
              {k === "circle" ? "Circle" : "Polygon"}
            </button>
          ))}
        </div>
        {kind === "circle" && (
          <label className="grid gap-1 text-sm">Radius: {radius >= 1000 ? `${(radius / 1000).toFixed(1)} km` : `${radius} m`}
            <input type="range" min={20} max={5000} step={10} value={radius} onChange={(e) => setRadius(Number(e.target.value))} />
          </label>
        )}
        {kind === "polygon" && (
          <span className="flex gap-2 text-sm">
            <button type="button" className="rounded-md border px-3 py-2" disabled={!ring.length} onClick={() => setRing((r) => r.slice(0, -1))}>Undo corner</button>
            <button type="button" className="rounded-md border px-3 py-2" disabled={!ring.length} onClick={() => setRing([])}>Clear</button>
          </span>
        )}
      </div>
      <MapView zones={drawn} points={points} center={centre ?? ring[0] ?? center} zoom={14} fit={false} onMapClick={click} height={380} />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <button type="button" className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50" disabled={busy || !!problem || !name.trim()} onClick={save}>
          {busy ? "Saving…" : zone ? "Save changes" : "Add zone"}
        </button>
        {problem && <span className="text-muted-foreground">{problem}</span>}
        {message && <span className={message.ok ? "text-foreground" : "text-destructive"} role="status">{message.text}</span>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ 3. the live monitor

export function GeofenceMonitor({ entity, zone, max = 30, label }: {
  entity: string; zone?: string; max?: number; label?: (c: Crossing) => string;
}) {
  const zones = useZones();
  const [items, setItems] = React.useState<Crossing[]>([]);
  const [state, setState] = React.useState<"connecting" | "live" | "reconnecting" | "denied">("connecting");
  const names = React.useMemo(() => new Map(zones.zones.map((z) => [z.id, z.name])), [zones.zones]);
  // A zone added after this screen opened is unknown here: look the zones up again, once, when its first crossing arrives.
  const known = React.useRef(names);
  known.current = names;
  const asked = React.useRef(new Set<string>());
  const reload = zones.reload;

  React.useEffect(() => {
    const q = `entity=${encodeURIComponent(entity)}${zone ? `&zone=${encodeURIComponent(zone)}` : ""}`;
    const line = new EventSource(`${BASE}/api/geofence/stream?${q}`);
    let opened = false;
    line.onopen = () => { opened = true; setState("live"); };
    line.onmessage = (m) => {
      try {
        const c = JSON.parse(m.data) as Crossing;
        if (!known.current.has(c.geofenceId) && !asked.current.has(c.geofenceId)) { asked.current.add(c.geofenceId); void reload(); }
        setItems((all) => (all.some((x) => x.id === c.id) ? all : [c, ...all].sort((a, b) => b.occurredAt - a.occurredAt).slice(0, max)));
      } catch { /* a half-sent line */ }
    };
    line.onerror = () => { setState(opened ? "reconnecting" : "denied"); };
    return () => line.close();
  }, [entity, zone, max, reload]);

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground" role="status">
        {state === "live" ? "Live" : state === "connecting" ? "Connecting…" : state === "reconnecting" ? "Reconnecting…" : "You may not watch these zones, or you are signed out."}
      </p>
      {items.length === 0 && state === "live" && <p className="text-sm text-muted-foreground">Nothing has crossed a zone yet.</p>}
      <ul className="divide-y rounded-xl border">
        {items.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm" data-crossing={c.type}>
            <span>{(label ?? describe)({ ...c, zoneName: c.zoneName ?? names.get(c.geofenceId) ?? null })}</span>
            <time className="shrink-0 text-xs text-muted-foreground">{clock(c.occurredAt)}</time>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ 4. the timeline

export function GeofenceEventTimeline({ entity, id, zone, limit = 50, showMap = true }: {
  entity: string; id?: string; zone?: string; limit?: number; showMap?: boolean;
}) {
  const [events, setEvents] = React.useState<Crossing[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const q = `entity=${encodeURIComponent(entity)}${id ? `&id=${encodeURIComponent(id)}` : ""}${zone ? `&zone=${encodeURIComponent(zone)}` : ""}&limit=${limit}`;
    let gone = false;
    call<{ events: Crossing[] }>(`/api/geofence/events?${q}`).then((r) => { if (!gone) setEvents(r.events); }, (e) => { if (!gone) setError(say(e)); });
    return () => { gone = true; };
  }, [entity, id, zone, limit]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!events) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!events.length) return <p className="text-sm text-muted-foreground">No zone crossings yet.</p>;
  const pins: MapPoint[] = events.map((c) => ({ id: c.id, lat: c.lat, lng: c.lng, label: describe(c), tone: TYPE_TONE[c.type] ?? "primary" }));
  return (
    <div className="space-y-3">
      {showMap && <MapView points={pins} height={240} />}
      <ol className="space-y-2 border-l pl-4">
        {events.map((c, i) => {
          const later = events[i - 1];
          const away = later ? Math.round(distanceM({ lat: c.lat, lng: c.lng }, { lat: later.lat, lng: later.lng })) : null;
          return (
            <li key={c.id} className="text-sm" data-crossing={c.type}>
              <div className="font-medium">{describe(c)}</div>
              <div className="text-xs text-muted-foreground">
                {new Date(c.occurredAt).toLocaleString()}
                {typeof c.metadata.distanceM === "number" ? ` · ${Math.abs(Number(c.metadata.distanceM))} m ${Number(c.metadata.distanceM) <= 0 ? "inside the edge" : "from the edge"}` : ""}
                {away != null ? ` · ${away} m from the next` : ""}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ 5. the settings

type RuleRow = Rule & { willWaitFor?: string | null };
const ON = [["geofence.entered", "enters"], ["geofence.exited", "leaves"], ["geofence.dwell", "stays"], ["geofence.approaching", "is approaching"]] as const;

export function GeofenceSettings({ zone, onSaved }: { zone: Zone; onSaved?: () => void }) {
  const [v, setV] = React.useState<Record<string, string>>(() => Object.fromEntries(["dwellSec", "approachM", "hysteresisM", "minFixes", "maxAccuracyM"].map((k) => [k, zone.rules[k] == null ? "" : String(zone.rules[k])])));
  const [active, setActive] = React.useState(zone.active);
  const [assign, setAssign] = React.useState(zone.assign.join(", "));
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [rules, setRules] = React.useState<RuleRow[] | null>(null);
  const [form, setForm] = React.useState({ onEvent: "geofence.entered", kind: "emit_event", event: "", role: "", title: "", confirm: "" });

  const loadRules = React.useCallback(() => {
    call<{ rules: RuleRow[] }>(`/api/geofence/rules?zone=${encodeURIComponent(zone.id)}`).then((r) => setRules(r.rules), () => setRules(null));
  }, [zone.id]);
  React.useEffect(loadRules, [loadRules]);

  const saveZone = async () => {
    const rulesOut: Record<string, number> = {};
    for (const [k, s] of Object.entries(v)) if (s.trim() !== "") rulesOut[k] = Number(s);
    try {
      await call(`/api/geofence/zones?id=${encodeURIComponent(zone.id)}`, { method: "PATCH", body: JSON.stringify({ rules: rulesOut, active, assign: assign.split(",").map((s) => s.trim()).filter(Boolean) }) });
      setMsg({ ok: true, text: "Saved." }); onSaved?.();
    } catch (e) { setMsg({ ok: false, text: say(e) }); }
  };

  const draft: Partial<Rule> = {
    onEvent: form.onEvent,
    action: form.kind === "emit_event" ? { kind: "emit_event", event: form.event } : { kind: "notify", title: form.title, role: form.role || undefined },
    confirm: form.confirm.trim() ? { event: form.confirm.trim() } : null,
  };
  const willBeHeld = isSensitive(draft as Rule);
  const addRule = async () => {
    try {
      const r = await call<{ warning?: string }>("/api/geofence/rules", { method: "POST", body: JSON.stringify({ ...draft, geofenceId: zone.id }) });
      setMsg({ ok: !r.warning, text: r.warning ?? "Rule added." });
      setForm({ ...form, event: "", title: "", confirm: "" });
      loadRules();
    } catch (e) { setMsg({ ok: false, text: say(e) }); }
  };
  const field = (k: string, label: string, hint: string) => (
    <label className="grid gap-1 text-sm" key={k}>{label}
      <input className="rounded-md border bg-background px-3 py-2" inputMode="numeric" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} placeholder={hint} />
    </label>
  );

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="font-medium">{zone.name}</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {field("dwellSec", "Stay counts after (seconds)", "off")}
          {field("approachM", "Approaching from (metres)", "off")}
          {field("hysteresisM", "Leaving needs this far outside (metres)", "10")}
          {field("minFixes", "Agreeing locations to count a crossing", "2")}
          {field("maxAccuracyM", "Ignore locations less accurate than (metres)", "100")}
          <label className="grid gap-1 text-sm">Watches (blank = everyone)
            <input className="rounded-md border bg-background px-3 py-2" value={assign} onChange={(e) => setAssign(e.target.value)} placeholder="Order:*, Driver:abc" />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active</label>
        <button type="button" className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground" onClick={saveZone}>Save settings</button>
      </section>

      <section className="space-y-3">
        <h3 className="font-medium">What happens</h3>
        {rules === null && <p className="text-sm text-muted-foreground">Rules are shown to zone managers.</p>}
        {rules?.length === 0 && <p className="text-sm text-muted-foreground">No rules yet.</p>}
        <ul className="space-y-2">
          {rules?.map((r) => (
            <li key={r.id} className="flex items-start justify-between gap-3 rounded-lg border p-3 text-sm">
              <div>
                <div>When it {ON.find(([e]) => e === r.onEvent)?.[1] ?? r.onEvent}: {r.action.kind === "emit_event" ? `send “${r.action.event}”` : `tell ${r.action.role ?? "people"}: “${r.action.title}”`}</div>
                {r.willWaitFor && <div className="text-xs text-muted-foreground">Waits for “{r.willWaitFor}” — being in the zone is not enough.</div>}
              </div>
              <button type="button" className="text-xs text-destructive" onClick={async () => { await call(`/api/geofence/rules?id=${r.id}`, { method: "DELETE" }).catch(() => undefined); loadRules(); }}>Remove</button>
            </li>
          ))}
        </ul>
        <div className="grid gap-3 rounded-lg border p-3 text-sm sm:grid-cols-2">
          <label className="grid gap-1">When it
            <select className="rounded-md border bg-background px-3 py-2" value={form.onEvent} onChange={(e) => setForm({ ...form, onEvent: e.target.value })}>
              {ON.map(([e, t]) => <option key={e} value={e}>{t}</option>)}
            </select>
          </label>
          <label className="grid gap-1">Then
            <select className="rounded-md border bg-background px-3 py-2" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="emit_event">send an event</option>
              <option value="notify">tell people</option>
            </select>
          </label>
          {form.kind === "emit_event"
            ? <label className="grid gap-1 sm:col-span-2">Event name<input className="rounded-md border bg-background px-3 py-2" value={form.event} onChange={(e) => setForm({ ...form, event: e.target.value })} placeholder="order.driver_arrived" /></label>
            : <>
                <label className="grid gap-1">Role<input className="rounded-md border bg-background px-3 py-2" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} placeholder="admin" /></label>
                <label className="grid gap-1">Message<input className="rounded-md border bg-background px-3 py-2" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Driver is here" /></label>
              </>}
          <label className="grid gap-1 sm:col-span-2">Only after this event (a confirmation that is not GPS){willBeHeld && " — required for this one"}
            <input className="rounded-md border bg-background px-3 py-2" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} placeholder="order.code_verified" />
          </label>
          {willBeHeld && !form.confirm.trim() && (
            <p className="sm:col-span-2 text-xs text-destructive">This moves money, finishes a job or marks someone present. Without a confirmation it will be saved but never run.</p>
          )}
          <div className="sm:col-span-2"><button type="button" className="rounded-md border px-4 py-2" onClick={addRule}>Add rule</button></div>
        </div>
      </section>
      {msg && <p className={"text-sm " + (msg.ok ? "" : "text-destructive")} role="status">{msg.text}</p>}
    </div>
  );
}
