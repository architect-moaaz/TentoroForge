/**
 * A GPS simulator for testing and demos: walks an entity along a path and produces the fixes a real phone would — with
 * noise, gaps, repeats, late arrivals and bad values. Seeded, so a failing run can be run again. No imports.
 * Forge runtime — do not remove.
 */

export type Point = { lat: number; lng: number };
export type SimFix = { entityId: string; entityType: string; lat: number; lng: number; at: number; accuracy?: number };

export type SimOptions = {
  entityId?: string;
  entityType?: string;
  /** Metres per second. */
  speedMps?: number;
  /** Seconds between fixes. */
  everySec?: number;
  /** Random sideways error in metres (a spread, not a limit). */
  jitterM?: number;
  /** Accuracy the "device" reports. */
  accuracy?: number;
  startAt?: number;
  seed?: number;
  /** Chance (0-1) a fix is delivered twice. */
  duplicateRate?: number;
  /** Chance a fix is held back and delivered a few fixes late. */
  lateRate?: number;
};

const M_PER_DEG = 111_320;

/** A small seeded random generator (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A point `metres` east and `northM` north of `from`. */
export function offset(from: Point, eastM: number, northM: number): Point {
  return { lat: from.lat + northM / M_PER_DEG, lng: from.lng + eastM / (M_PER_DEG * Math.cos((from.lat * Math.PI) / 180)) };
}

function metres(a: Point, b: Point): number {
  const dy = (b.lat - a.lat) * M_PER_DEG;
  const dx = (b.lng - a.lng) * M_PER_DEG * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dx, dy);
}

/** The fixes of a walk along `path` (corners are visited in order), in the order they happen. */
export function walk(path: Point[], o: SimOptions = {}): SimFix[] {
  const rand = rng(o.seed ?? 1);
  const speed = o.speedMps ?? 8;
  const step = o.everySec ?? 5;
  const out: SimFix[] = [];
  let t = o.startAt ?? 1_700_000_000_000;
  const emit = (p: Point) => {
    const j = o.jitterM ?? 0;
    const q = j > 0 ? offset(p, (rand() - 0.5) * 2 * j, (rand() - 0.5) * 2 * j) : p;
    out.push({ entityId: o.entityId ?? "e1", entityType: o.entityType ?? "driver", lat: q.lat, lng: q.lng, at: t, accuracy: o.accuracy });
  };
  emit(path[0]);
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const len = metres(a, b);
    const n = Math.max(1, Math.round(len / (speed * step)));
    for (let k = 1; k <= n; k++) {
      t += step * 1000;
      emit({ lat: a.lat + ((b.lat - a.lat) * k) / n, lng: a.lng + ((b.lng - a.lng) * k) / n });
    }
  }
  return o.duplicateRate || o.lateRate ? scramble(out, rand, o.duplicateRate ?? 0, o.lateRate ?? 0) : out;
}

/** Standing still at `p` for `seconds`. */
export function stay(p: Point, seconds: number, o: SimOptions = {}): SimFix[] {
  return walk([p, p], { ...o, speedMps: 1, everySec: o.everySec ?? 5 }).slice(0, 1).concat(
    Array.from({ length: Math.floor(seconds / (o.everySec ?? 5)) }, (_, i) => {
      const rand = rng((o.seed ?? 1) + i + 7);
      const j = o.jitterM ?? 0;
      const q = j > 0 ? offset(p, (rand() - 0.5) * 2 * j, (rand() - 0.5) * 2 * j) : p;
      return { entityId: o.entityId ?? "e1", entityType: o.entityType ?? "driver", lat: q.lat, lng: q.lng, at: (o.startAt ?? 1_700_000_000_000) + (i + 1) * (o.everySec ?? 5) * 1000, accuracy: o.accuracy };
    }),
  );
}

/** Repeats some fixes and delays others by a few places. */
export function scramble<T>(fixes: T[], rand: () => number, duplicateRate: number, lateRate: number): T[] {
  const out: T[] = [];
  const held: { at: number; fix: T }[] = [];
  fixes.forEach((f, i) => {
    if (rand() < lateRate) held.push({ at: i + 2 + Math.floor(rand() * 3), fix: f });
    else { out.push(f); if (rand() < duplicateRate) out.push(f); }
    for (const h of [...held]) if (h.at <= i) { out.push(h.fix); held.splice(held.indexOf(h), 1); }
  });
  for (const h of held) out.push(h.fix);
  return out;
}

/** A device on the edge: alternates just inside and just outside a point, the case that makes naive geofences flap. */
export function oscillate(edge: Point, insideDir: { eastM: number; northM: number }, times: number, o: SimOptions & { amplitudeM?: number } = {}): SimFix[] {
  const amp = o.amplitudeM ?? 6;
  const len = Math.hypot(insideDir.eastM, insideDir.northM) || 1;
  const ux = insideDir.eastM / len, uy = insideDir.northM / len;
  const out: SimFix[] = [];
  let t = o.startAt ?? 1_700_000_000_000;
  for (let i = 0; i < times; i++) {
    const s = i % 2 === 0 ? amp : -amp;
    const p = offset(edge, ux * s, uy * s);
    out.push({ entityId: o.entityId ?? "e1", entityType: o.entityType ?? "driver", lat: p.lat, lng: p.lng, at: t, accuracy: o.accuracy });
    t += (o.everySec ?? 5) * 1000;
  }
  return out;
}
