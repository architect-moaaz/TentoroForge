"""Blueprint scoreboard — the fast regression tier.

Why a second scoreboard
-----------------------
``scripts/fleet.py`` + ``services/scorecard.py`` already measure generation
quality across a fixture fleet, and that harness is the best thing the old
platform built: it turns "did this change make things worse" into a number.

But it scores *generated applications*, so every reading costs an LLM run and a
build. During a rebuild of the substrate itself — schema, IDs, capabilities,
the verification matrix — that is too slow to gate anything, and a signal you
cannot afford to run is a signal you do not have.

This module scores the **Blueprint** instead. It is pure, deterministic and
runs in milliseconds with no model call, because everything it needs is already
computed by :mod:`services.blueprint.verification`. It does not replace the
app-level fleet run; it sits underneath it:

    tier 1 (here)      Blueprint coherence      ms, no LLM      every change
    tier 2 (fleet.py)  generated-app quality    minutes + LLM   before a release

What it measures
----------------
Each metric is ``ok / total`` over the artifacts the metric can apply to, so a
Blueprint with no widgets is not penalised for widget problems — it reports
``—`` for that metric, matching the existing baseline table. The composite is
the mean of the metrics that are defined.

The metrics are derived from the §75 matrix rather than invented, so the
scoreboard and the verification pass can never disagree about what "good"
means.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from services.blueprint.verification import verify

FLEET_DIR = Path(__file__).resolve().parents[2] / "fleet" / "blueprints"
BASELINE_PATH = Path(__file__).resolve().parents[2] / "fleet" / "blueprint-baselines.json"


def _entities(doc: dict) -> list[dict]:
    return doc.get("data", {}).get("entities", []) or []


def _live(items: Iterable[dict] | None) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _approved(items: Iterable[dict] | None) -> list[dict]:
    """Requirements still PROPOSED owe nothing yet (§22)."""
    return [i for i in _live(items) if i.get("status") != "PROPOSED"]


# ---------------------------------------------------------------------------
# Metrics — each returns (ok, total). total == 0 means "not applicable".
# ---------------------------------------------------------------------------

def _m_traceability(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Approved requirements that some artifact claims (Requirement↔Code)."""
    reqs = _approved(doc.get("requirements"))
    return sum(1 for r in reqs if r.get("id") not in flagged), len(reqs)


def _m_tested(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Approved requirements a test verifies (Requirement↔Test)."""
    reqs = _approved(doc.get("requirements"))
    verified: set[str] = set()
    for t in _live(doc.get("tests")):
        verified.update(t.get("verifies") or [])
    return sum(1 for r in reqs if r.get("id") in verified), len(reqs)


def _m_guarded(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Mutating endpoints carrying a permission (API↔Permission, §100)."""
    from services.blueprint.verification import MUTATING
    apis = [a for a in _live(doc.get("apis")) if a.get("method") in MUTATING]
    return sum(1 for a in apis if a.get("permission")), len(apis)


def _m_grounded(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Endpoints pointing at a real entity (API↔Database)."""
    known = {e.get("id") for e in _entities(doc)}
    apis = [a for a in _live(doc.get("apis")) if a.get("entity")]
    return sum(1 for a in apis if a["entity"] in known), len(apis)


def _m_reachable(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """List and dashboard pages reachable from navigation (Navigation↔Page)."""
    pages = [p for p in _live(doc.get("pages"))
             if p.get("pattern") in ("entity_list", "dashboard")]
    return sum(1 for p in pages if p.get("id") not in flagged), len(pages)


def _m_wired(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Manual workflows with something that launches them (Page↔Workflow)."""
    flows = [w for w in _live(doc.get("workflows"))
             if (w.get("trigger") or {}).get("kind") == "manual"]
    return sum(1 for w in flows if w.get("id") not in flagged), len(flows)


def _m_bound(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Widgets whose data contract holds up (Widget↔DataSource)."""
    widgets = _live(doc.get("widgets"))
    return sum(1 for w in widgets if w.get("id") not in flagged), len(widgets)


def _m_implemented(doc: dict, flagged: set[str]) -> tuple[int, int]:
    """Artifacts claiming to be built that say where (Blueprint↔Implementation)."""
    built = ("IMPLEMENTED", "VERIFYING", "VERIFIED")
    arts = [a for section in ("pages", "apis", "workflows", "components")
            for a in _live(doc.get(section)) if a.get("status") in built]
    return sum(1 for a in arts if a.get("id") not in flagged), len(arts)


#: Each metric reads findings from exactly one §75 edge. Sharing a global
#: "anything flagged" set would make the metrics dependent: a single unguarded
#: endpoint would drag down `implemented` too, and one defect would be counted
#: twice in the composite.
METRICS: dict[str, tuple[str, Callable[[dict, set[str]], tuple[int, int]]]] = {
    "traceability": ("Requirement↔Code", _m_traceability),
    "tested": ("Requirement↔Test", _m_tested),
    "guarded": ("API↔Permission", _m_guarded),
    "grounded": ("API↔Database", _m_grounded),
    "reachable": ("Navigation↔Page", _m_reachable),
    "wired": ("Page↔Workflow", _m_wired),
    "bound": ("Widget↔DataSource", _m_bound),
    "implemented": ("Blueprint↔Implementation", _m_implemented),
}

METRIC_ORDER = tuple(METRICS)


@dataclass
class Score:
    app: str
    valid: bool = True
    metrics: dict[str, float | None] = field(default_factory=dict)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    composite: float = 0.0
    findings: int = 0
    by_edge: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app, "valid": self.valid, "composite": self.composite,
            "findings": self.findings,
            "metrics": self.metrics, "counts": self.counts,
            "by_edge": self.by_edge, "errors": self.errors[:20],
        }


def score(doc: dict, *, app: str = "app") -> Score:
    """Score one Blueprint. Pure — reads, computes, changes nothing."""
    report = verify(doc)
    by_edge = report.by_edge()
    flagged_for: dict[str, set[str]] = {
        edge: {f.artifact_id for f in items if f.artifact_id}
        for edge, items in by_edge.items()
    }

    s = Score(app=app, findings=len(report.findings),
              by_edge={e: len(v) for e, v in sorted(by_edge.items())})

    defined: list[float] = []
    for name, (edge, fn) in METRICS.items():
        ok, total = fn(doc, flagged_for.get(edge, set()))
        s.counts[name] = {"ok": ok, "total": total}
        if total == 0:
            s.metrics[name] = None
            continue
        ratio = ok / total
        s.metrics[name] = round(ratio, 4)
        defined.append(ratio)

    s.composite = round(sum(defined) / len(defined), 4) if defined else 0.0
    return s


def score_validated(doc: dict, *, app: str = "app") -> Score:
    """Score, but fail the Blueprint outright if it breaks the schema contract.

    An invalid Blueprint scoring 0.9 on coherence would be a lie: the document
    cannot be generated from at all.
    """
    from jsonschema import Draft7Validator

    from services.blueprint.service import CONTRACT_PATH

    validator = Draft7Validator(json.loads(CONTRACT_PATH.read_text("utf-8")))
    errors = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
              for e in validator.iter_errors(doc)]
    if errors:
        return Score(app=app, valid=False, composite=0.0, errors=errors)
    return score(doc, app=app)


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------

def load_fleet(directory: str | Path = FLEET_DIR) -> dict[str, dict]:
    d = Path(directory)
    if not d.exists():
        return {}
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(d.glob("*.json"))}


def score_fleet(directory: str | Path = FLEET_DIR) -> dict[str, Score]:
    return {name: score_validated(doc, app=name)
            for name, doc in load_fleet(directory).items()}


# ---------------------------------------------------------------------------
# Regression gate
# ---------------------------------------------------------------------------

@dataclass
class Regression:
    app: str
    metric: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return round(self.after - self.before, 4)

    def __str__(self) -> str:
        return (f"{self.app}.{self.metric}: {self.before:.3f} → {self.after:.3f} "
                f"({self.delta:+.3f})")


class ScoreRegression(AssertionError):
    """A fleet score moved backwards."""


def compare(
    baseline: dict[str, Any],
    current: dict[str, Score],
    *,
    tolerance: float = 0.0,
) -> list[Regression]:
    """Every metric that got worse by more than ``tolerance``.

    Missing fixtures count as a regression: silently dropping a fixture is the
    easiest way to make a scoreboard go green.
    """
    out: list[Regression] = []
    for app, base in baseline.items():
        if app not in current:
            out.append(Regression(app, "<missing>", float(base.get("composite", 0)), 0.0))
            continue
        now = current[app]
        if not now.valid:
            out.append(Regression(app, "<invalid>", float(base.get("composite", 0)), 0.0))
            continue
        for metric in ("composite",) + METRIC_ORDER:
            before = base.get("composite") if metric == "composite" else \
                (base.get("metrics") or {}).get(metric)
            after = now.composite if metric == "composite" else now.metrics.get(metric)
            if before is None or after is None:
                continue
            if after < before - tolerance:
                out.append(Regression(app, metric, float(before), float(after)))
    return out


def assert_no_regression(
    baseline: dict[str, Any],
    current: dict[str, Score],
    *,
    tolerance: float = 0.0,
) -> None:
    losses = compare(baseline, current, tolerance=tolerance)
    if losses:
        raise ScoreRegression(
            f"{len(losses)} score regression(s):\n  "
            + "\n  ".join(str(r) for r in losses)
        )


def load_baseline(path: str | Path = BASELINE_PATH) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def bless(scores: dict[str, Score], path: str | Path = BASELINE_PATH) -> Path:
    """Write the current scores as the new baseline.

    Deliberately a separate, explicit action: a harness that re-blesses itself
    on every run cannot detect a regression.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {k: v.to_dict() for k, v in sorted(scores.items())}, indent=2, sort_keys=True
    ) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Rendering — same column vocabulary as docs/scoreboard/baseline-*.txt
# ---------------------------------------------------------------------------

def render_table(scores: dict[str, Score], baseline: dict[str, Any] | None = None) -> str:
    baseline = baseline or {}
    cols = METRIC_ORDER
    head = f"{'app':<18}" + "".join(f"{c[:9]:>11}" for c in cols) + f"{'composite':>11}{'Δ':>8}"
    lines = [head, "-" * len(head)]
    for name, s in sorted(scores.items(), key=lambda kv: kv[1].composite):
        if not s.valid:
            lines.append(f"{name:<18}{'INVALID — fails the schema contract':<{len(head) - 18}}")
            continue
        row = f"{name:<18}"
        for c in cols:
            v = s.metrics.get(c)
            row += f"{'—':>11}" if v is None else f"{v * 100:>11.1f}"
        row += f"{s.composite * 100:>11.1f}"
        base = (baseline.get(name) or {}).get("composite")
        row += f"{'':>8}" if base is None else f"{(s.composite - base) * 100:>+8.1f}"
        lines.append(row)
    return "\n".join(lines)
