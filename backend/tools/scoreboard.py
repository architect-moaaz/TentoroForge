"""Score a generated app against what it was actually asked to be.

This is a MEASUREMENT, not a pipeline stage. It lives in ``tools/`` and
not ``services/`` on purpose: nothing in generation may import it, and
it must never repair anything. It reads a finished output directory and
returns numbers. If it ever starts writing to the app, it has become
the ninety-first guard and should be deleted.

The metrics come from one sentence — the app was supposed to be *rich
UI/UX pages with the buttons and clickables bound to the right action*
— decomposed into things that can be counted without an LLM:

  coverage   planned pages that actually shipped as page schemas
  reach      shipped routes a user can navigate to from the menu
  wired      clickables that carry any action at all (vs dead buttons)
  resolves   actions whose target actually exists (route / workflow)
  bound      data components naming a resource that exists
  forms      forms with a submit target

Each is a rate in [0,1] over a denominator that this app actually has;
a metric with no denominator is reported as ``None`` and excluded from
the composite rather than scored as 1.0. An app with no forms is not
better at forms than an app whose forms all work.

Deliberately NOT scored here: anything needing a running server or a
browser. Those belong in the live pass. This has to stay fast enough
to run over every app in ``output/`` in one go, because the point is a
baseline across many apps, not a verdict on one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

# ── metric definitions ──────────────────────────────────────────────
# Order matters: it's the column order in the report.
METRICS = ("coverage", "reach", "wired", "resolves", "bound", "forms")

# Reported alongside the metrics but NOT part of the composite: a count,
# not a rate, and mixing "how many junk routes" into an average of
# percentages would be meaningless.
DIAGNOSTICS = ("dupe_routes",)


@dataclass
class Metric:
    """One rate plus the raw counts behind it.

    Keeping numerator/denominator (not just the rate) is what makes the
    aggregate honest: averaging per-app rates over-weights an app with
    three buttons against one with two hundred.
    """

    ok: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        return None if self.total == 0 else self.ok / self.total


@dataclass
class AppScore:
    app: str
    metrics: dict[str, Metric]
    composite: float | None
    note: str = ""
    dupe_routes: int = 0

    def row(self) -> dict[str, Any]:
        out: dict[str, Any] = {"app": self.app}
        for m in METRICS:
            met = self.metrics.get(m)
            out[m] = None if met is None else met.rate
        out["composite"] = self.composite
        return out


# ── small readers (tolerant: a missing file is a zero, never a crash) ─

def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _norm(route: str) -> str:
    r = str(route or "").strip()
    if not r.startswith("/"):
        r = "/" + r
    return r.rstrip("/") or "/"


_PARAM = re.compile(r"\[[^\]]+\]")


def _pattern(route: str) -> str:
    """Collapse dynamic segments so /bills/[id] and /bills/42 compare equal."""
    return _PARAM.sub("*", _norm(route))


def _shipped_routes(root: Path) -> set[str]:
    """Routes that exist as page schemas, as route patterns.

    ``src/schemas/bills/[id].json`` → ``/bills/*``. Both the schema tree
    and the Next app tree are consulted: some routes ship as .tsx only
    (auth, tasks), and calling those missing would be wrong.
    """
    routes: set[str] = set()
    sdir = root / "src" / "schemas"
    if sdir.is_dir():
        for p in sdir.rglob("*.json"):
            rel = p.relative_to(sdir).with_suffix("")
            slug = "/".join(rel.parts)
            if slug in ("shell", "index"):
                continue
            routes.add(_pattern("/" + slug))
    adir = root / "src" / "app"
    if adir.is_dir():
        for p in adir.rglob("page.tsx"):
            rel_parts = p.relative_to(adir).parent.parts
            # A catch-all ([...slug]) is the renderer's dispatcher, not a
            # page. Counting it made every app look like it shipped a
            # route called "/*" that no menu could possibly link to.
            if any(seg.startswith("[...") for seg in rel_parts):
                continue
            parts = [
                seg for seg in rel_parts
                # (group) segments are Next routing groups, not URL segments
                if not (seg.startswith("(") and seg.endswith(")"))
            ]
            routes.add(_pattern("/" + "/".join(parts)) if parts else "/")
    # Same reasoning for anything that collapsed to pure wildcards.
    return {r for r in routes if r.strip("/*") or r == "/"}


def _menu_routes(root: Path) -> set[str]:
    """Every route the app's chrome links to, as patterns.

    The menu does not live in one place. Sidebar/topbar frames put it in
    ``shell.json`` as a SideNav tree. The ``persona-pills`` frame puts a
    pill per persona in shell.json and leaves the per-persona screen row
    to the template's PersonaChrome, which reads ``nav-flow.personas``
    at runtime — so those routes are navigable but appear nowhere in the
    shell. Reading only shell.json scored every persona-pills app near
    zero, which was a bug in this scorer, not in those apps.
    """
    found: set[str] = set()
    shell = _load(root / "src" / "schemas" / "shell.json")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("href", "navigate", "to", "route", "path"):
                v = node.get(key)
                if isinstance(v, str) and v.startswith("/"):
                    found.add(_pattern(v))
            props = node.get("props")
            if isinstance(props, dict):
                walk(props)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)

    walk(shell)

    # Persona chrome: every job/screen route of every persona is a link
    # in the rendered sub-nav row, even though the shell only carries
    # one pill per persona.
    for cand in ("src/contracts/nav-flow.json", "contracts/nav-flow.json"):
        nav = _load(root / cand)
        if not isinstance(nav, dict):
            continue
        for persona in (nav.get("personas") or []):
            if not isinstance(persona, dict):
                continue
            for key in ("jobs", "screens"):
                for entry in (persona.get(key) or []):
                    if isinstance(entry, dict):
                        r = entry.get("route")
                        if isinstance(r, str) and r.startswith("/"):
                            found.add(_pattern(r))
                    elif isinstance(entry, str) and entry.startswith("/"):
                        found.add(_pattern(entry))
        break
    return found


def _workflow_names(root: Path) -> set[str]:
    """Workflow ids/names the app actually ships, lowercased."""
    names: set[str] = set()
    plan = _load(root / "src" / "contracts" / "plan.json") or {}
    for wf in (plan.get("workflows") or []):
        if isinstance(wf, dict):
            for k in ("name", "id", "slug"):
                v = wf.get(k)
                if isinstance(v, str) and v:
                    names.add(v.strip().lower())
    for sub in ("src/workflows", "workflows"):
        d = root / sub
        if d.is_dir():
            for p in d.rglob("*.json"):
                names.add(p.stem.strip().lower())
                doc = _load(p)
                if isinstance(doc, dict):
                    for k in ("name", "id"):
                        v = doc.get(k)
                        if isinstance(v, str) and v:
                            names.add(v.strip().lower())
    return names


def _resource_names(root: Path) -> set[str]:
    """Entity/table/slug names that exist, lowercased.

    Union of plan entities and the resource registry, because the two
    disagree on casing and pluralisation often enough that checking
    only one produces false failures.
    """
    out: set[str] = set()

    def add(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            out.add(v.strip().lower())
            out.add(v.strip().lower().rstrip("s"))

    plan = _load(root / "src" / "contracts" / "plan.json") or {}
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for k, v in ents.items():
            add(k)
            if isinstance(v, dict):
                for kk in ("name", "table", "slug"):
                    add(v.get(kk))
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                for kk in ("name", "table", "slug"):
                    add(e.get(kk))
            else:
                add(e)

    for cand in (root / "contracts" / "resource-registry.json",
                 root / "src" / "contracts" / "resource-registry.json"):
        reg = _load(cand)
        if isinstance(reg, dict):
            for key in ("resources", "entities"):
                block = reg.get(key)
                if isinstance(block, dict):
                    for k, v in block.items():
                        add(k)
                        if isinstance(v, dict):
                            for kk in ("name", "table", "slug", "entity"):
                                add(v.get(kk))
                elif isinstance(block, list):
                    for e in block:
                        if isinstance(e, dict):
                            for kk in ("name", "table", "slug", "entity"):
                                add(e.get(kk))
    return out


def _case_dupes(shipped: set[str]) -> set[str]:
    """Routes that are only a naming-convention variant of another route.

    Generation emits both the slug route (``/bills/new``) and an
    entity-cased twin (``/Bill/new``) often enough that it dominates the
    reachability numbers. They are junk — nothing links to them and the
    slug route already serves the job — but they are a *naming* defect,
    not a *navigation* one. Separating them keeps ``reach`` about menus.

    A route is the dupe when a lowercase-and-pluralised sibling exists
    and it is not itself already lowercase. Conservative on purpose: it
    only fires when the twin is actually present.
    """
    dupes: set[str] = set()
    for r in shipped:
        segs = r.split("/")
        if not any(s[:1].isupper() for s in segs if s):
            continue
        lowered = "/".join(s.lower() for s in segs)
        for cand in (lowered, re.sub(r"(?<=[a-z])(?=/|$)", "s", lowered, count=1)):
            twin = _norm(cand)
            if twin != r and twin in shipped:
                dupes.add(r)
                break
        else:
            # Try pluralising the first non-empty segment: /Bill/new → /bills/new
            if len(segs) > 1 and segs[1]:
                alt = "/" + segs[1].lower() + "s" + ("/" + "/".join(segs[2:]) if len(segs) > 2 else "")
                if _norm(alt) in shipped:
                    dupes.add(r)
    return dupes


def _parent(route: str) -> str | None:
    """The route one level up, or None at the root."""
    segs = [s for s in _norm(route).split("/") if s]
    if not segs:
        return None
    return "/" + "/".join(segs[:-1]) if len(segs) > 1 else "/"


def _reachable_set(shipped: set[str], menu: set[str]) -> set[str]:
    """Routes a user can actually arrive at, by closure from the menu.

    An earlier version of this asked only "is this route (or an ancestor
    of it) in the menu", and scored ~1,100 routes across the corpus as
    unreachable. Two thirds of those were ``/new``, ``/*`` and ``/edit``
    pages — which are of course not in the menu; you reach them from the
    list page's New button, a row click, or an Edit button. Counting
    them as navigation failures conflated "the user can't get here" with
    "the button might be missing", and the second is what ``wired`` and
    ``resolves`` already measure.

    So: seed with the menu, then repeatedly admit any shipped route
    whose parent route is already reachable. ``/bills/[id]/edit`` is
    reachable when ``/bills/[id]`` is, which is reachable when
    ``/bills`` is in the menu. What survives is a genuine orphan: a page
    with no menu entry and no parent page anywhere above it.
    """
    reachable = {r for r in shipped if r in menu} | {"/"} & shipped
    # A menu entry may name a route that ships only as a pattern (e.g.
    # menu says /bills/42, app ships /bills/*) — admit those too.
    for r in shipped:
        if any(_route_exists(m, {r}) for m in menu):
            reachable.add(r)
    # The root is deliberately NOT a conferring parent. Every route's
    # ancestry ends at "/", and "/" is in every menu, so treating it as
    # a parent made the whole app reachable by construction and the
    # metric read 100% for every app — vacuous. A dashboard does not
    # link to every section; the menu does. So a top-level route has to
    # earn its place in the menu, while a CHILD route inherits from its
    # own list page, which really does carry the button that opens it.
    changed = True
    while changed:
        changed = False
        for r in sorted(shipped - reachable):
            p = _parent(r)
            while p and p != "/":
                if p in reachable:
                    reachable.add(r)
                    changed = True
                    break
                p = _parent(p)
    return reachable


def _route_exists(target: str, shipped: set[str]) -> bool:
    """A navigate target resolves if some shipped route matches it.

    Compared as patterns, so ``/bills/42`` satisfies ``/bills/*``. A
    prefix match counts too: ``/bills/42/history`` is served by the
    catch-all under ``/bills/*`` in this renderer.
    """
    t = _pattern(target)
    if t in shipped:
        return True
    for r in shipped:
        if r.endswith("*") and t.startswith(r[:-1]):
            return True
    return False


# ── the scorer ──────────────────────────────────────────────────────

def score_app(output_dir: str | Path) -> AppScore:
    """Score one generated app. Never raises; a broken app scores low."""
    root = Path(output_dir)
    name = root.name
    metrics = {m: Metric() for m in METRICS}

    plan = _load(root / "src" / "contracts" / "plan.json")
    if not isinstance(plan, dict):
        return AppScore(name, metrics, None, note="no plan.json")

    shipped = _shipped_routes(root)
    if not shipped:
        return AppScore(name, metrics, None, note="no page schemas")

    # ── coverage: planned pages that shipped ────────────────────────
    for pg in (plan.get("pages") or []):
        if not isinstance(pg, dict):
            continue
        r = pg.get("route")
        if not isinstance(r, str) or not r.startswith("/"):
            continue
        metrics["coverage"].total += 1
        if _route_exists(r, shipped):
            metrics["coverage"].ok += 1
        else:
            metrics["coverage"].failures.append(f"planned {r} never shipped")

    # ── reach: shipped routes reachable from the menu ───────────────
    # Detail/child routes are reached from their parent list, not the
    # menu, so a route counts as reachable when the menu names it OR
    # names an ancestor. Auth and system routes are excluded: nobody
    # puts /login in the nav, and counting it as unreachable is noise.
    menu = _menu_routes(root)
    dupes = _case_dupes(shipped)
    reachable = _reachable_set(shipped, menu)
    _EXCLUDE = ("/login", "/signup", "/logout", "/forbidden", "/maintenance", "/error")
    for r in sorted(shipped):
        if any(r.startswith(x) for x in _EXCLUDE) or r in dupes:
            continue
        metrics["reach"].total += 1
        if r in reachable:
            metrics["reach"].ok += 1
        else:
            metrics["reach"].failures.append(f"{r} is an orphan (no menu entry, no parent page)")

    # ── interaction-derived metrics ─────────────────────────────────
    try:
        from services.interaction_extractor import extract_interactions
        interactions = extract_interactions(root)
    except Exception as exc:  # noqa: BLE001
        return AppScore(name, metrics, _composite(metrics),
                        note=f"interaction extract failed: {type(exc).__name__}")

    workflows = _workflow_names(root)
    resources = _resource_names(root)

    for it in interactions:
        kind = getattr(it, "kind", "")

        if kind == "button":
            act = getattr(it, "action", None)
            akind = getattr(act, "kind", "none") if act else "none"
            label = (getattr(it, "label", "") or "?")[:40]
            route = getattr(it, "route", "?")

            metrics["wired"].total += 1
            if akind and akind != "none":
                metrics["wired"].ok += 1
            else:
                metrics["wired"].failures.append(f"{route}: '{label}' has no action")
                continue  # a dead button has no target to resolve

            # Only targets we can check count toward `resolves`; a
            # 'compute' or 'submit' action has no external referent.
            if akind == "navigate":
                tgt = getattr(act, "navigate_target", None)
                if tgt:
                    metrics["resolves"].total += 1
                    if _route_exists(tgt, shipped):
                        metrics["resolves"].ok += 1
                    else:
                        metrics["resolves"].failures.append(
                            f"{route}: '{label}' → {tgt} (no such route)")
            elif akind == "workflow":
                tgt = getattr(act, "workflow_target", None)
                if tgt:
                    metrics["resolves"].total += 1
                    if tgt.strip().lower() in workflows:
                        metrics["resolves"].ok += 1
                    else:
                        metrics["resolves"].failures.append(
                            f"{route}: '{label}' → workflow {tgt} (not defined)")

        elif kind == "form":
            sub = getattr(it, "submit", None)
            skind = getattr(sub, "kind", "none") if sub else "none"
            route = getattr(it, "route", "?")
            metrics["forms"].total += 1
            if skind and skind != "none":
                metrics["forms"].ok += 1
            else:
                metrics["forms"].failures.append(f"{route}: form has no submit target")
            if skind == "workflow":
                tgt = getattr(sub, "workflow_target", None)
                if tgt:
                    metrics["resolves"].total += 1
                    if tgt.strip().lower() in workflows:
                        metrics["resolves"].ok += 1
                    else:
                        metrics["resolves"].failures.append(
                            f"{route}: form → workflow {tgt} (not defined)")

        elif kind == "list":
            route = getattr(it, "route", "?")
            ent = getattr(it, "entity", None)
            ds = getattr(it, "dataSource", "?")
            metrics["bound"].total += 1
            if ent and str(ent).strip().lower() in resources:
                metrics["bound"].ok += 1
            elif ent:
                metrics["bound"].failures.append(
                    f"{route}: {ds} → entity '{ent}' not in registry")
            else:
                metrics["bound"].failures.append(
                    f"{route}: dataSource '{ds}' resolves to no entity")

    return AppScore(name, metrics, _composite(metrics), dupe_routes=len(dupes))


def _composite(metrics: dict[str, Metric]) -> float | None:
    """Mean of the metrics this app actually has a denominator for.

    Unweighted on purpose. Weighting invites arguing about the weights
    instead of about the app; if one metric matters more, read that
    column.
    """
    rates = [m.rate for m in metrics.values() if m.rate is not None]
    return sum(rates) / len(rates) if rates else None


# ── batch + reporting ───────────────────────────────────────────────

def score_all(output_root: str | Path) -> list[AppScore]:
    root = Path(output_root)
    apps = [d for d in sorted(root.iterdir())
            if d.is_dir() and (d / "src" / "contracts" / "plan.json").is_file()]
    return [score_app(d) for d in apps]


def _pct(v: float | None) -> str:
    return "  —  " if v is None else f"{v * 100:5.1f}"


def render_table(scores: Iterable[AppScore]) -> str:
    scores = list(scores)
    head = f"{'app':<14}" + "".join(f"{m:>10}" for m in METRICS) + f"{'composite':>11}" + f"{'dupes':>8}"
    lines = [head, "-" * len(head)]
    for s in sorted(scores, key=lambda x: (x.composite is None, x.composite or 0)):
        row = f"{s.app[:14]:<14}"
        for m in METRICS:
            row += f"{_pct(s.metrics[m].rate):>10}"
        row += f"{_pct(s.composite):>11}" + f"{s.dupe_routes:>8}"
        if s.note:
            row += f"   ({s.note})"
        lines.append(row)

    # Pooled aggregate: sum numerators over sum denominators, so one
    # 200-button app can't be outvoted by ten 3-button apps.
    lines.append("-" * len(head))
    pooled = f"{'POOLED':<14}"
    for m in METRICS:
        ok = sum(s.metrics[m].ok for s in scores)
        tot = sum(s.metrics[m].total for s in scores)
        pooled += f"{_pct(None if tot == 0 else ok / tot):>10}"
    comps = [s.composite for s in scores if s.composite is not None]
    pooled += f"{_pct(sum(comps) / len(comps) if comps else None):>11}"
    pooled += f"{sum(s.dupe_routes for s in scores):>8}"
    lines.append(pooled)
    lines.append(f"\n{len(scores)} app(s) scored; rates are percentages.")
    return "\n".join(lines)


def top_failures(scores: Iterable[AppScore], limit: int = 12) -> str:
    """Most common failure shapes across the corpus — what to fix first."""
    from collections import Counter
    buckets: Counter = Counter()
    for s in scores:
        for m, met in s.metrics.items():
            for f in met.failures:
                # Strip app-specific nouns to cluster by shape.
                shape = re.sub(r"'[^']*'", "'X'", f)
                shape = re.sub(r"/[A-Za-z0-9._\[\]-]+", "/X", shape)
                buckets[f"{m}: {shape}"] += 1
    lines = ["", "Most common failure shapes:"]
    for shape, n in buckets.most_common(limit):
        lines.append(f"  {n:>5}  {shape}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Score generated apps (read-only).")
    ap.add_argument("apps", nargs="*", help="app dirs; default: all under --output-root")
    ap.add_argument("--output-root", default="../output")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--failures", action="store_true", help="show failure shapes")
    a = ap.parse_args(argv)

    scores = [score_app(p) for p in a.apps] if a.apps else score_all(a.output_root)
    print(render_table(scores))
    if a.failures:
        print(top_failures(scores))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {s.app: {**s.row(),
                     "counts": {m: {"ok": s.metrics[m].ok, "total": s.metrics[m].total}
                                for m in METRICS},
                     "failures": {m: s.metrics[m].failures[:40] for m in METRICS}}
             for s in scores}, indent=2), encoding="utf-8")
        print(f"\nwrote {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
