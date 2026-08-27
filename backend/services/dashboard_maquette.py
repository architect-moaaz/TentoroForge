"""Dashboard maquette — the content-decision step that produces rich dashboards.

This is the missing seam between planning and page authoring. It runs
ONCE per app, takes the plan as input, and returns a structured JSON
maquette that spells out:

  * Which entities become the 3-4 KPI tiles, what operation + filter each
    binds to, what label they show.
  * What primary chart tells the domain's story (bar/line/donut over
    which entity+group).
  * What activity feed to surface (which entity, which time window).
  * What hero framing (photo subject + greeting pattern).
  * Optional secondary sections (kanban preview, recent list, gauge).

The downstream `build_dashboard_page(plan, maquette)` in
`services.deterministic_pages` consumes this and emits a real schema
with real bindings — no LLM in the assembly, no min-viable fallback.

Fails closed: if the LLM call errors or the response is unparseable,
returns None and the caller falls back to the pre-existing dashboard
authoring path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────── data shapes ──────────────────────────────


# Slice A / KPI anatomy — the shared op-vocabulary for a KPI value or
# any of its breakdown lines. Anything outside this set is silently
# dropped at parse time so the composer never has to reason about a
# shape it can't emit as a data source.
_KPI_OPS = frozenset({"count", "sum", "avg", "max"})


@dataclass
class KPIBreakdownSpec:
    """A sub-line under the primary KPI value, e.g. "Male 984".

    Each breakdown row is bound to its own data source (same op-vocabulary
    as the parent KPI). Composer wires each row to a MetricTile
    ``breakdown[]`` prop entry with the value pre-formatted as a
    ``{{source_name}}`` binding.
    """

    label: str
    entity: str
    op: str  # "count" | "sum" | "avg" | "max"
    field: Optional[str] = None
    filter: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"label": self.label, "entity": self.entity, "op": self.op}
        if self.field:
            d["field"] = self.field
        if self.filter:
            d["filter"] = self.filter
        return d


@dataclass
class KPIThresholdSpec:
    """Colouring rule applied to the primary value.

    - ``warn_above`` — value above this → renderer stamps
      ``data-threshold="warn"``.
    - ``critical_above`` — value above this → ``data-threshold="critical"``
      (wins over warn).
    - ``color_on_value`` — when True the renderer also applies a text
      colour override on the value itself; when False the data attr is
      the only signal (custom CSS can pick it up).
    """

    warn_above: Optional[float] = None
    critical_above: Optional[float] = None
    color_on_value: bool = False

    def to_dict(self) -> dict:
        d: dict = {}
        if self.warn_above is not None:
            d["warn_above"] = self.warn_above
        if self.critical_above is not None:
            d["critical_above"] = self.critical_above
        d["color_on_value"] = self.color_on_value
        return d


@dataclass
class KPIExtremesSpec:
    """Max/min companion labels rendered as extra breakdown rows.

    The composer resolves the actual values via the KPI's parent entity
    + field (op:max / op:min synthesised at compose time). Only the
    labels live in the maquette — values are always derived.
    """

    max_label: Optional[str] = None
    min_label: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.max_label:
            d["max_label"] = self.max_label
        if self.min_label:
            d["min_label"] = self.min_label
        return d


@dataclass
class KPISpec:
    """One MetricTile — real entity + operation + filter."""

    label: str
    entity: str
    op: str  # "count" | "sum" | "avg" | "max"
    field: Optional[str] = None  # required for sum/avg/max
    filter: Optional[str] = None  # human-readable filter like "status=active"
    trend_window: Optional[str] = None  # e.g. "week" / "month" for delta
    format: str = "number"  # renderer MetricTile requires: number|currency|percent|duration
    # Slice A anatomy (all optional; missing = today's render).
    # dataclasses.field(...) qualified because the KPI has a member
    # NAMED `field` above which shadows the imported `field` factory
    # inside the class body at annotation-eval time.
    breakdown: list[KPIBreakdownSpec] = dataclasses.field(default_factory=list)
    threshold: Optional[KPIThresholdSpec] = None
    extremes: Optional[KPIExtremesSpec] = None

    def to_dict(self) -> dict:
        d = {"label": self.label, "entity": self.entity, "op": self.op,
             "format": self.format}
        if self.field:
            d["field"] = self.field
        if self.filter:
            d["filter"] = self.filter
        if self.trend_window:
            d["trend_window"] = self.trend_window
        # Anatomy keys ONLY appear when populated so downstream JSON
        # diffs stay clean for legacy KPIs.
        if self.breakdown:
            d["breakdown"] = [b.to_dict() for b in self.breakdown]
        if self.threshold is not None:
            d["threshold"] = self.threshold.to_dict()
        if self.extremes is not None:
            d["extremes"] = self.extremes.to_dict()
        return d


_CHART_KINDS = frozenset({"bar", "line", "area", "donut"})
_OVERLAY_KINDS = frozenset({"line", "bar", "area"})
_ENCODING_SORT = frozenset({"asc", "desc"})


@dataclass
class ChartOverlaySpec:
    """A secondary chart type + series drawn on the SAME axes as the
    primary. Enables bar+line combos like the Banking "Transactions
    Yearly and Time Trend" moment.
    """

    kind: str            # "line" | "bar" | "area"
    aggregate: str = "count"
    aggregate_field: Optional[str] = None
    curve: Optional[str] = None  # "straight" | "smooth"

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "aggregate": self.aggregate}
        if self.aggregate_field:
            d["aggregate_field"] = self.aggregate_field
        if self.curve:
            d["curve"] = self.curve
        return d


@dataclass
class ChartViewToggle:
    """One chip in the chart-header segmented-button group. The
    ``modifier`` is opaque to the composer — passed through to the
    runtime as a query-widener."""

    label: str
    modifier: dict = dataclasses.field(default_factory=dict)
    default: bool = False

    def to_dict(self) -> dict:
        d: dict = {"label": self.label, "modifier": dict(self.modifier)}
        if self.default:
            d["default"] = True
        return d


@dataclass
class ChartEncodingSpec:
    """Visual-grammar switches on the primary chart."""

    leaderboard: bool = False
    stacked: bool = False
    sorted: Optional[str] = None  # "asc" | "desc"
    top_n: Optional[int] = None
    value_labels: bool = False

    def to_dict(self) -> dict:
        d: dict = {}
        if self.leaderboard: d["leaderboard"] = True
        if self.stacked:     d["stacked"] = True
        if self.sorted:      d["sorted"] = self.sorted
        if self.top_n:       d["top_n"] = self.top_n
        if self.value_labels: d["value_labels"] = True
        return d


@dataclass
class ChartSemanticColorSpec:
    """Cross-widget color consistency — bind a data field's values to
    stable colors so `Male` reads pink on every chart on this page."""

    field: str
    map: dict = dataclasses.field(default_factory=dict)  # value → color

    def to_dict(self) -> dict:
        return {"by": "field", "field": self.field, "map": dict(self.map)}


@dataclass
class ChartSpec:
    """Primary chart — bound to op:series."""

    kind: str  # "bar" | "line" | "area" | "donut"
    title: str
    entity: str
    group_by: str  # column to group series by (usually a date/enum)
    aggregate: str = "count"  # "count" | "sum"
    aggregate_field: Optional[str] = None  # required for sum
    window: Optional[str] = None  # "week" | "month"
    # ── Slice A / Chart anatomy (all optional; missing = today's render)
    help: Optional[str] = None
    overlay: Optional[ChartOverlaySpec] = None
    view_toggles: list[ChartViewToggle] = dataclasses.field(default_factory=list)
    encoding: Optional[ChartEncodingSpec] = None
    semantic_color: Optional[ChartSemanticColorSpec] = None

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "title": self.title, "entity": self.entity,
             "group_by": self.group_by, "aggregate": self.aggregate}
        if self.aggregate_field:
            d["aggregate_field"] = self.aggregate_field
        if self.window:
            d["window"] = self.window
        # Anatomy keys ONLY appear when populated so downstream JSON
        # diffs stay clean for legacy charts.
        if self.help:
            d["help"] = self.help
        if self.overlay is not None:
            d["overlay"] = self.overlay.to_dict()
        if self.view_toggles:
            d["view_toggles"] = [t.to_dict() for t in self.view_toggles]
        if self.encoding is not None:
            enc = self.encoding.to_dict()
            if enc:
                d["encoding"] = enc
        if self.semantic_color is not None:
            d["semantic_color"] = self.semantic_color.to_dict()
        return d


@dataclass
class ActivitySpec:
    """ActivityFeed — recent inserts on an entity."""

    entity: str
    title: str
    limit: int = 5
    order_by: str = "createdAt"

    def to_dict(self) -> dict:
        return {"entity": self.entity, "title": self.title,
                "limit": self.limit, "order_by": self.order_by}


# Allowed values for HeroSpec.kind — the composer maps each to a
# different rendering: "photo-greeting" is the legacy default (Hero
# component with backgroundImage + greeting), the others let the LLM
# author more distinctive moments per app so two same-domain dashboards
# don't collapse to the same "photo + welcome" pattern.
HERO_KINDS = (
    "photo-greeting",      # legacy default — full-bleed photo + headline
    "personalised-greeting",  # text-only, name / role-driven ("Welcome back, Rania")
    "editorial-quote",     # centred pull-quote + attribution
    "kpi-strip",           # small headline + the KPI row promoted into the hero
    "balance-rings",       # for balance/quota domains (leave, credits, budget)
)

# Allowed values for DashboardMaquette.section_rhythm — controls the
# Stack `gap` between top-level sections. "tight" = dense info-density
# (fintech, admin); "cozy" = the default balanced feel; "generous" =
# editorial / consumer / wellness. The composer maps to spacing tokens.
SECTION_RHYTHMS = ("tight", "cozy", "generous")

# Ornament kinds — small decorative flourishes the composer sprinkles
# between sections so two same-domain dashboards read differently even
# when the KPIs happen to align. Deliberately curated to primitives the
# design system already ships (see IllustratedEmpty catalog + Divider
# variants) — no free-form asset paths.
ORNAMENT_KINDS = (
    "eyebrow-line",        # thin accent line above the first heading
    "corner-illustration", # small illustration tucked into the hero corner
    "section-divider",     # decorative divider between sections
    "accent-badge",        # tiny badge under the hero for texture
)

# Empty-state illustration keys — same catalog as collection maquette.
# Dashboards use these when their primary data source is genuinely empty
# on a fresh install (before the first entity is created).
_DASHBOARD_ILLUSTRATIONS = (
    "welcome-mat", "clipboard-blank", "empty-inbox", "planted-seed",
    "sunlit-window", "workshop-bench", "map-with-pin", "storefront-open",
)

# Footer kinds — the last visual moment on the dashboard.
DASHBOARD_FOOTER_KINDS = (
    "support-links",   # links row (docs / help / contact)
    "attribution",     # subtle "Powered by …" / brand mark
    "next-steps",      # small "next actions" card
    "insight",         # editorial callout (Peak day / week-in-review)
)


@dataclass
class HeroSpec:
    """Hero header — kind decides layout, other fields fill the slot.

    ``photo_subject`` is required for ``kind="photo-greeting"`` (the
    default); other kinds may leave it empty. ``greeting`` is required
    for every kind except ``editorial-quote`` (which uses ``quote`` +
    ``attribution``).
    """

    photo_subject: str = ""   # required for kind="photo-greeting"
    greeting: str = ""        # required except for kind="editorial-quote"
    subhead: Optional[str] = None
    kind: str = "photo-greeting"
    # Editorial-quote-specific slots — populated when kind ==
    # "editorial-quote". Ignored by other kinds.
    quote: Optional[str] = None
    attribution: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.photo_subject:
            d["photo_subject"] = self.photo_subject
        if self.greeting:
            d["greeting"] = self.greeting
        if self.subhead:
            d["subhead"] = self.subhead
        if self.quote:
            d["quote"] = self.quote
        if self.attribution:
            d["attribution"] = self.attribution
        return d


@dataclass
class DashboardEmptyStateSpec:
    """Empty-state moment for the dashboard when the primary data source
    has no rows yet — the first thing a fresh-install user sees.

    Different from a collection empty-state (which sits inside a Table's
    body): dashboard empty-state IS the whole page, so headline + CTA
    matter more than the illustration.
    """

    illustration: str  # one of _DASHBOARD_ILLUSTRATIONS
    headline: str
    subhead: Optional[str] = None
    cta_label: Optional[str] = None
    cta_action: Optional[str] = None  # workflow id / route

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"illustration": self.illustration, "headline": self.headline}
        for k in ("subhead", "cta_label", "cta_action"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


@dataclass
class OrnamentSpec:
    """A small decorative flourish sprinkled between sections."""

    kind: str  # one of ORNAMENT_KINDS
    placement: Optional[str] = None  # "before-hero" | "after-kpis" | "after-chart" | "before-footer"
    illustration: Optional[str] = None  # for kind="corner-illustration"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.placement:
            d["placement"] = self.placement
        if self.illustration:
            d["illustration"] = self.illustration
        return d


@dataclass
class DashboardFooterSpec:
    """Optional footer band beneath the dashboard sections."""

    kind: str  # one of DASHBOARD_FOOTER_KINDS
    content: Optional[str] = None  # copy for insight / attribution / next-steps

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.content:
            d["content"] = self.content
        return d


# Slice C — section chrome. See docs/superpowers/specs/
# 2026-08-15-widget-anatomy-composition-recipes.md
FILTER_KINDS: frozenset[str] = frozenset({"select", "date-range", "text"})


@dataclass
class FilterSpec:
    """One filter in the dashboard's filter bar.

    - ``kind`` — one of :data:`FILTER_KINDS`. Unknown kinds are dropped
      at parse time so the composer never renders a shape it can't emit.
    - ``field`` — the column this filter narrows (composer binds it to
      the widgets' dataSources via URL query params).
    - ``label`` — human-facing label ("Loan Risk", "Date range").
    - ``options`` — enum values for ``kind="select"``; empty for other
      kinds. Non-string entries are silently dropped.
    """

    kind: str
    field: str
    label: str
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind":    self.kind,
            "field":   self.field,
            "label":   self.label,
            "options": list(self.options),
        }


@dataclass
class DashboardMaquette:
    """The whole content spec for one dashboard.

    Phase 2 additions (rich decisions + moments layer):

    - :attr:`signature_moves` — LLM picks 1-3 signature-move ids from the
      catalog (see ``archetypes/signature_moves.json``). The composer
      emits them as ``data-signature-move`` attributes on the page-root
      Stack so downstream design-critic + renderer variants can key off
      them without a schema shape change.
    - :attr:`section_rhythm` — density hint mapping to Stack ``gap``.
      One of :data:`SECTION_RHYTHMS`.
    - :attr:`empty_state` — first-run empty moment when the primary data
      source has no rows. Composer renders as `IllustratedEmpty` at the
      top of the page.
    - :attr:`ornament` — small decorative flourish between sections
      (eyebrow line, corner illustration, decorative divider). Composer
      places based on ``placement``.
    - :attr:`footer` — support-links / attribution / next-steps card
      beneath the last section.

    Slice C — section chrome (2026-08-15):

    - :attr:`subtitle` — one-line editorial subtitle under the H1
      ("Evaluating batch processing across archivists"). Absent = skip.
    - :attr:`filters` — list[FilterSpec] rendered as a top filter bar
      whose state syncs to URL query params.
    - :attr:`reset_filters` — bool; when True the chrome adds a
      "↺ Reset all filters" chip aligned right of the header.
    """

    kpis: list[KPISpec] = field(default_factory=list)
    primary_chart: Optional[ChartSpec] = None
    activity: Optional[ActivitySpec] = None
    hero: Optional[HeroSpec] = None
    signature_moves: list[str] = field(default_factory=list)
    section_rhythm: str = "cozy"
    empty_state: Optional[DashboardEmptyStateSpec] = None
    ornament: Optional[OrnamentSpec] = None
    footer: Optional[DashboardFooterSpec] = None
    # ── Slice C — chrome (all optional, backwards-safe) ────────────────
    subtitle: Optional[str] = None
    filters: list[FilterSpec] = field(default_factory=list)
    reset_filters: bool = False

    def to_dict(self) -> dict:
        return {
            "kpis": [k.to_dict() for k in self.kpis],
            "primary_chart": self.primary_chart.to_dict() if self.primary_chart else None,
            "activity": self.activity.to_dict() if self.activity else None,
            "hero": self.hero.to_dict() if self.hero else None,
            "signature_moves": list(self.signature_moves),
            "section_rhythm": self.section_rhythm,
            "empty_state": self.empty_state.to_dict() if self.empty_state else None,
            "ornament": self.ornament.to_dict() if self.ornament else None,
            "footer": self.footer.to_dict() if self.footer else None,
            # Slice C — chrome fields serialise verbatim; missing values
            # take safe defaults on the receiving side so a legacy JSON
            # dict without them parses identically.
            "subtitle": self.subtitle,
            "filters": [f.to_dict() for f in self.filters],
            "reset_filters": self.reset_filters,
        }

    @classmethod
    def from_dict(cls, obj: dict) -> "DashboardMaquette":
        """Parse an LLM response into a DashboardMaquette. Missing/invalid
        fields are dropped (never raise) so the caller can decide whether
        the partial result meets its richness contract."""
        m = cls()
        if not isinstance(obj, dict):
            return m
        for k in obj.get("kpis") or []:
            if not isinstance(k, dict):
                continue
            label = k.get("label")
            entity = k.get("entity")
            op = k.get("op")
            if not (isinstance(label, str) and label and
                    isinstance(entity, str) and entity and
                    isinstance(op, str) and op in _KPI_OPS):
                continue
            kpi = KPISpec(
                label=label, entity=entity, op=op,
                field=k.get("field") if isinstance(k.get("field"), str) else None,
                filter=k.get("filter") if isinstance(k.get("filter"), str) else None,
                trend_window=k.get("trend_window") if isinstance(k.get("trend_window"), str) else None,
            )
            # ── Slice A / KPI anatomy ─────────────────────────────
            # breakdown — sub-lines under the primary value. Same
            # discipline as the parent KPI (label + entity + op) so the
            # composer can author one data source per row.
            raw_bd = k.get("breakdown")
            if isinstance(raw_bd, list):
                for br in raw_bd:
                    if not isinstance(br, dict):
                        continue
                    b_label = br.get("label")
                    b_entity = br.get("entity")
                    b_op = br.get("op")
                    if not (isinstance(b_label, str) and b_label and
                            isinstance(b_entity, str) and b_entity and
                            isinstance(b_op, str) and b_op in _KPI_OPS):
                        continue
                    kpi.breakdown.append(KPIBreakdownSpec(
                        label=b_label, entity=b_entity, op=b_op,
                        field=br.get("field") if isinstance(br.get("field"), str) else None,
                        filter=br.get("filter") if isinstance(br.get("filter"), str) else None,
                    ))
            # threshold — numeric bounds only. An object with no
            # numeric bounds is functionally absent → drop entirely
            # so the composer never emits hollow chrome.
            raw_th = k.get("threshold")
            if isinstance(raw_th, dict):
                wa = raw_th.get("warn_above")
                ca = raw_th.get("critical_above")
                wa_num = wa if isinstance(wa, (int, float)) and not isinstance(wa, bool) else None
                ca_num = ca if isinstance(ca, (int, float)) and not isinstance(ca, bool) else None
                col = raw_th.get("color_on_value")
                col_bool = col if isinstance(col, bool) else False
                if wa_num is not None or ca_num is not None:
                    kpi.threshold = KPIThresholdSpec(
                        warn_above=wa_num,
                        critical_above=ca_num,
                        color_on_value=col_bool,
                    )
            # extremes — max/min labels. Values are derived at compose
            # time; only the labels ride in the maquette.
            raw_ex = k.get("extremes")
            if isinstance(raw_ex, dict):
                mx = raw_ex.get("max_label") if isinstance(raw_ex.get("max_label"), str) else None
                mn = raw_ex.get("min_label") if isinstance(raw_ex.get("min_label"), str) else None
                if mx or mn:
                    kpi.extremes = KPIExtremesSpec(max_label=mx, min_label=mn)
            m.kpis.append(kpi)
        pc = obj.get("primary_chart")
        if isinstance(pc, dict):
            if all(isinstance(pc.get(k), str) and pc.get(k)
                   for k in ("kind", "title", "entity", "group_by")):
                chart = ChartSpec(
                    kind=pc["kind"], title=pc["title"], entity=pc["entity"],
                    group_by=pc["group_by"],
                    aggregate=pc.get("aggregate") if isinstance(pc.get("aggregate"), str) else "count",
                    aggregate_field=pc.get("aggregate_field") if isinstance(pc.get("aggregate_field"), str) else None,
                    window=pc.get("window") if isinstance(pc.get("window"), str) else None,
                )
                # ── Slice A / Chart anatomy ─────────────────────────
                if isinstance(pc.get("help"), str) and pc["help"].strip():
                    chart.help = pc["help"].strip()

                # overlay — secondary chart on shared axes
                raw_ov = pc.get("overlay")
                if isinstance(raw_ov, dict):
                    ov_kind = raw_ov.get("kind")
                    if isinstance(ov_kind, str) and ov_kind in _OVERLAY_KINDS:
                        chart.overlay = ChartOverlaySpec(
                            kind=ov_kind,
                            aggregate=raw_ov.get("aggregate") if isinstance(raw_ov.get("aggregate"), str) else "count",
                            aggregate_field=raw_ov.get("aggregate_field") if isinstance(raw_ov.get("aggregate_field"), str) else None,
                            curve=raw_ov.get("curve") if isinstance(raw_ov.get("curve"), str) and raw_ov.get("curve") in {"straight", "smooth"} else None,
                        )

                # view_toggles — chart-header segmented buttons
                raw_vt = pc.get("view_toggles")
                if isinstance(raw_vt, list):
                    for t in raw_vt:
                        if not isinstance(t, dict):
                            continue
                        t_label = t.get("label")
                        if not (isinstance(t_label, str) and t_label.strip()):
                            continue
                        mod = t.get("modifier") if isinstance(t.get("modifier"), dict) else {}
                        chart.view_toggles.append(ChartViewToggle(
                            label=t_label.strip(),
                            modifier=dict(mod),
                            default=bool(t.get("default")),
                        ))

                # encoding — visual grammar flags
                raw_enc = pc.get("encoding")
                if isinstance(raw_enc, dict):
                    enc = ChartEncodingSpec()
                    enc.leaderboard = bool(raw_enc.get("leaderboard"))
                    enc.stacked = bool(raw_enc.get("stacked"))
                    if isinstance(raw_enc.get("sorted"), str) and raw_enc["sorted"] in _ENCODING_SORT:
                        enc.sorted = raw_enc["sorted"]
                    if isinstance(raw_enc.get("top_n"), int) and raw_enc["top_n"] > 0:
                        enc.top_n = raw_enc["top_n"]
                    enc.value_labels = bool(raw_enc.get("value_labels"))
                    # Only attach when something's set (empty encoding = None)
                    if (enc.leaderboard or enc.stacked or enc.sorted
                            or enc.top_n or enc.value_labels):
                        chart.encoding = enc

                # semantic_color — field→color map for cross-widget consistency
                raw_sc = pc.get("semantic_color")
                if isinstance(raw_sc, dict) and raw_sc.get("by") == "field":
                    sc_field = raw_sc.get("field")
                    sc_map = raw_sc.get("map")
                    if isinstance(sc_field, str) and sc_field.strip() and isinstance(sc_map, dict):
                        cleaned_map = {k: v for k, v in sc_map.items()
                                       if isinstance(k, str) and isinstance(v, str)}
                        if cleaned_map:
                            chart.semantic_color = ChartSemanticColorSpec(
                                field=sc_field.strip(), map=cleaned_map,
                            )

                m.primary_chart = chart
        act = obj.get("activity")
        if isinstance(act, dict):
            if isinstance(act.get("entity"), str) and isinstance(act.get("title"), str):
                m.activity = ActivitySpec(
                    entity=act["entity"], title=act["title"],
                    limit=act.get("limit", 5) if isinstance(act.get("limit"), int) else 5,
                    order_by=act.get("order_by", "createdAt") if isinstance(act.get("order_by"), str) else "createdAt",
                )
        hero = obj.get("hero")
        if isinstance(hero, dict):
            kind = hero.get("kind") if isinstance(hero.get("kind"), str) else "photo-greeting"
            # Unknown kind → drop back to the safe default so the composer
            # never has to reason about a shape it doesn't emit.
            if kind not in HERO_KINDS:
                kind = "photo-greeting"
            # Per-kind required-field checks. Missing required field →
            # skip the hero rather than emit a broken one.
            greeting = hero.get("greeting") if isinstance(hero.get("greeting"), str) else ""
            photo = hero.get("photo_subject") if isinstance(hero.get("photo_subject"), str) else ""
            quote = hero.get("quote") if isinstance(hero.get("quote"), str) else None
            attribution = hero.get("attribution") if isinstance(hero.get("attribution"), str) else None
            valid = True
            if kind == "photo-greeting":
                # Back-compat: legacy shape without `kind` set — needs both.
                if not (photo and greeting):
                    valid = False
            elif kind == "editorial-quote":
                if not quote:
                    valid = False
            else:  # personalised-greeting, kpi-strip, balance-rings
                if not greeting:
                    valid = False
            if valid:
                m.hero = HeroSpec(
                    kind=kind,
                    photo_subject=photo,
                    greeting=greeting,
                    subhead=hero.get("subhead") if isinstance(hero.get("subhead"), str) else None,
                    quote=quote,
                    attribution=attribution,
                )

        # Signature moves — LLM picks 1-3 ids from the catalog. Filter
        # to strings only; downstream composer emits them verbatim as
        # `data-signature-move` attribute values, and a later phase
        # (design critic) checks each actually corresponds to a catalog
        # entry. Silently dropping non-strings here keeps the composer
        # simple.
        for sm in obj.get("signature_moves") or []:
            if isinstance(sm, str) and sm.strip():
                m.signature_moves.append(sm.strip())

        rhythm = obj.get("section_rhythm")
        if isinstance(rhythm, str) and rhythm in SECTION_RHYTHMS:
            m.section_rhythm = rhythm

        # ── Empty state ────────────────────────────────────────────────
        # First-run moment when the dashboard has no data yet. Requires a
        # headline; unknown illustration falls back to "welcome-mat" so
        # the composer always has a valid asset key.
        empty = obj.get("empty_state")
        if isinstance(empty, dict):
            headline = empty.get("headline")
            if isinstance(headline, str) and headline.strip():
                illustration = empty.get("illustration") if isinstance(empty.get("illustration"), str) else "welcome-mat"
                if illustration not in _DASHBOARD_ILLUSTRATIONS:
                    illustration = "welcome-mat"
                m.empty_state = DashboardEmptyStateSpec(
                    illustration=illustration,
                    headline=headline.strip(),
                    subhead=empty.get("subhead") if isinstance(empty.get("subhead"), str) else None,
                    cta_label=empty.get("cta_label") if isinstance(empty.get("cta_label"), str) else None,
                    cta_action=empty.get("cta_action") if isinstance(empty.get("cta_action"), str) else None,
                )

        # ── Ornament ───────────────────────────────────────────────────
        # Small decorative flourish. Unknown kind → drop (composer would
        # otherwise have to reason about a shape it doesn't emit).
        ornament = obj.get("ornament")
        if isinstance(ornament, dict):
            kind = ornament.get("kind")
            if isinstance(kind, str) and kind in ORNAMENT_KINDS:
                m.ornament = OrnamentSpec(
                    kind=kind,
                    placement=ornament.get("placement") if isinstance(ornament.get("placement"), str) else None,
                    illustration=ornament.get("illustration") if isinstance(ornament.get("illustration"), str) else None,
                )

        # ── Footer ────────────────────────────────────────────────────
        footer = obj.get("footer")
        if isinstance(footer, dict):
            kind = footer.get("kind")
            if isinstance(kind, str) and kind in DASHBOARD_FOOTER_KINDS:
                m.footer = DashboardFooterSpec(
                    kind=kind,
                    content=footer.get("content") if isinstance(footer.get("content"), str) else None,
                )

        # ── Slice C — section chrome ─────────────────────────────────
        # Subtitle: strip + reject empty so composer never emits a blank
        # Text node. Non-string values silently ignored.
        sub = obj.get("subtitle")
        if isinstance(sub, str) and sub.strip():
            m.subtitle = sub.strip()

        # Filters: list of FilterSpec dicts. Unknown kinds and rows
        # missing field+label are silently dropped — same discipline as
        # every other maquette section (composer only sees shapes it can
        # render).
        raw_filters = obj.get("filters")
        if isinstance(raw_filters, list):
            for fr in raw_filters:
                if not isinstance(fr, dict):
                    continue
                kind = fr.get("kind")
                field_ = fr.get("field")
                label = fr.get("label")
                if not (isinstance(kind, str) and kind in FILTER_KINDS):
                    continue
                if not (isinstance(field_, str) and field_.strip()):
                    continue
                if not (isinstance(label, str) and label.strip()):
                    continue
                raw_opts = fr.get("options")
                opts: list[str] = []
                if isinstance(raw_opts, list):
                    opts = [o for o in raw_opts if isinstance(o, str) and o.strip()]
                m.filters.append(FilterSpec(
                    kind=kind, field=field_.strip(), label=label.strip(),
                    options=opts,
                ))

        # Reset filters — bool only, no truthy coercion (a stray "yes"
        # string shouldn't materialise a Reset chip).
        rf = obj.get("reset_filters")
        if isinstance(rf, bool):
            m.reset_filters = rf

        return m


# ─────────────────────────── contract check ────────────────────────────


def meets_richness_contract(
    m: DashboardMaquette,
    *,
    require_kpi_row: bool = True,
    require_primary_chart: bool = True,
    require_activity_feed: bool = True,
    require_hero: bool = True,
    min_kpis: int = 3,
) -> list[str]:
    """Return a list of missing-requirement labels. Empty → contract met."""
    missing: list[str] = []
    if require_kpi_row and len(m.kpis) < min_kpis:
        missing.append(f"kpi_row(need ≥{min_kpis}, got {len(m.kpis)})")
    if require_primary_chart and m.primary_chart is None:
        missing.append("primary_chart")
    if require_activity_feed and m.activity is None:
        missing.append("activity_feed")
    if require_hero and m.hero is None:
        missing.append("hero")
    return missing


# ─────────────────────────── the LLM call ──────────────────────────────


def _build_system_prompt() -> str:
    return """\
You are the dashboard content director. Given an app plan (entities +
description), decide the DASHBOARD's content — WHAT to show, not how to
render it. The rendering is deterministic downstream. Your job is
judgment: which 3-4 numbers matter, what story the primary chart tells,
what recent activity a user needs to see, what the hero conveys.

OUTPUT CONTRACT
Emit ONE JSON object exactly matching this shape (no markdown fences):

{
  "kpis": [                    // 3-4 tiles, ordered most-important first
    {
      "label": "Human-readable label",
      "entity": "<entity_name from plan.entities>",
      "op": "count" | "sum" | "avg" | "max",
      "field": "<column>",     // required for sum/avg/max, omit for count
      "filter": "<optional>",  // e.g. "status=active", "date=today"
      "trend_window": "week",  // optional — enables Δ vs previous window

      // ── Slice A / KPI anatomy (all optional; missing = bare tile) ───
      // Anatomy makes a stat card tell a story. A bare "Total 2,000"
      // says less than "Total 2,000 / Male 984 / Female 1,016".
      "breakdown": [
        // 1-3 sub-lines under the primary value. Each has its own
        // op/entity/field/filter — the composer authors a real data
        // source per row. Use when the value's COMPOSITION matters:
        //   - "Clients 2,000" needs Male/Female split.
        //   - "Total Debt $127M" needs Max/Min extremes (use `extremes`
        //     for that — cleaner than hand-authoring two breakdown rows).
        //   - "Transactions 157,224" needs Pass/Failed split.
        // Do NOT add breakdown when the primary value already tells
        // the whole story (a bare "Batches Queued 0" doesn't).
        { "label": "Male",   "entity": "customer", "op": "count",
          "filter": "gender=M" },
        { "label": "Female", "entity": "customer", "op": "count",
          "filter": "gender=F" }
      ],
      "threshold": {
        // Colour the primary value when it crosses a threshold.
        // Applies to numeric KPIs where "high is bad" — DTI ratios,
        // failure counts, latency, backlog size. Skip for KPIs where
        // "high is good" (revenue, sign-ups).
        "warn_above":     50,      // → data-threshold="warn"  (amber)
        "critical_above": 100,     // → data-threshold="critical" (red)
        "color_on_value": true     // paint the value text; false =
                                    // data-attr only (custom CSS keys off it)
      },
      "extremes": {
        // Max + min companion labels; values are DERIVED from the
        // KPI's own entity + field (op:max / op:min). Only labels here.
        // Requires the parent KPI to have a `field` (bare counts skipped).
        // Example: on "Total Debt $127M" → "Single Max Debt $516K /
        // Single Min Debt $5".
        "max_label": "Single Max Debt",
        "min_label": "Single Min Debt"
      }
    }, ...
  ],
  "primary_chart": {
    "kind": "bar" | "line" | "area" | "donut",
    "title": "Chart title",
    "entity": "<entity>",
    "group_by": "<column>",    // usually a date column, sometimes an enum
    "aggregate": "count" | "sum",
    "aggregate_field": "<column>",   // required if aggregate=sum
    "window": "week" | "month",      // optional restriction
    // ── Slice A / Chart anatomy (all optional; skip when not needed) ──
    "help": "Debt-to-income above 40% is flagged risky",
      // One-liner shown in a hover popover on the chart header. Use
      // when the value needs interpretation the axes don't reveal.
    "overlay": {
      // Draws a SECOND encoding on the SAME axes. Use only when two
      // series tell one story together (Amount + #Transactions on the
      // same time axis). One overlay max — more would need a legend.
      "kind": "line" | "bar" | "area",
      "aggregate": "count" | "sum",
      "aggregate_field": "<column>",
      "curve": "smooth"                // smooth | straight
    },
    "view_toggles": [
      // Chart-header segmented buttons that swap a query modifier at
      // runtime. Use when the reader would naturally toggle between
      // "Time Trend / Year Trend" or "Amount / Count" views. Max 3.
      { "label": "Time Trend", "modifier": { "window": "month" } },
      { "label": "Year Trend", "modifier": { "window": "year" }, "default": true }
    ],
    "encoding": {
      // Grammar switches. `leaderboard` re-lays the chart as a ranked
      // horizontal bar with value annotations (Banking "Top States by
      // Transaction Amount" shape). Use for top-N ranking screens.
      "leaderboard":  false,
      "stacked":      false,
      "sorted":       "desc" | "asc",   // optional
      "top_n":        10,               // optional (leaderboard usually pairs with this)
      "value_labels": true              // put values on the bars themselves
    },
    "semantic_color": {
      // Cross-widget color consistency. When two charts on the page
      // both split by `gender`, the same value lands the same color.
      "by":    "field",
      "field": "gender",
      "map":   { "M": "var(--male)", "F": "var(--female)" }
    }
  },
  "activity": {
    "entity": "<entity>",
    "title": "Latest bookings",
    "limit": 5,
    "order_by": "createdAt"    // usually createdAt desc
  },
  "hero": {
    "kind": "photo-greeting" | "personalised-greeting" | "editorial-quote"
          | "kpi-strip" | "balance-rings",
    // Photo-greeting: full-bleed image + headline. Requires photo_subject + greeting.
    // Personalised-greeting: text-only greeting keyed to the user
    //   ("Welcome back, Rania"). Requires greeting.
    // Editorial-quote: pull-quote + attribution. Requires quote (+ optional attribution).
    // Kpi-strip: small headline + KPI row promoted into the hero band. Requires greeting.
    // Balance-rings: for quota/balance domains (leave, credits, budget).
    //   Requires greeting; downstream composer wires to first entity with numeric quota.
    "photo_subject": "yoga studio interior at golden hour",  // photo-greeting only
    "greeting": "Welcome back — {n} classes booked today",
    "subhead": "optional secondary line",
    "quote": "Show up for yourself.",       // editorial-quote only
    "attribution": "— Rania, founder"       // editorial-quote only
  },
  "signature_moves": [
    // 1-3 signature-move ids that distinguish this dashboard. See
    // archetypes/signature_moves.json for the catalog. Examples:
    //   "sparkline-preview", "personalised-greeting", "activity-avatar-strip",
    //   "kanban-column-counts", "pull-to-refresh".
    // Pick moves that fit the DOMAIN + brief personality. Don't repeat
    // the same 2-3 moves for every app.
  ],
  "section_rhythm": "tight" | "cozy" | "generous",
    // Density hint the composer maps to Stack gap. "tight" = dense
    // (fintech/admin), "cozy" = balanced default, "generous" = editorial
    // / consumer / wellness. Pick based on the brief's personality.
  //
  // ── Section chrome (Slice C — 2026-08-15) ──────────────────────────
  // These three fields put a header block above the dashboard sections
  // so each dashboard reads as an editorial page with a subtitle + a
  // filter bar, not a bare heading + widget grid. All optional; the
  // safe absence produces no chrome.
  "subtitle": "Evaluating batch processing across archivists",
    // One-line editorial subtitle under the H1. Write it from the
    // BRIEF'S own vocabulary — not "Dashboard overview" or "Home
    // page". The Banking suite uses "Evaluating Our Current Clients
    // Demographics", "Evaluating Our Current Financial Health",
    // "Evaluating Financial Transactions" — each subtitle names what
    // the reader is evaluating. Omit if the domain doesn't warrant
    // one (a minimal ops tool with self-explanatory KPIs is fine
    // without).
  "filters": [
    // 0-4 cross-widget filters rendered at the top of the page.
    // Every widget below can narrow its dataSource by the filter
    // field. Pick filters that the primary reader would toggle to
    // ask a follow-up question ("show me Q4", "just failed batches").
    // Do NOT add filters when there's no obvious refinement question.
    { "kind": "select",     "field": "status",
      "label": "Status",       "options": ["queued","processing","complete"] },
    { "kind": "date-range", "field": "createdAt",
      "label": "Date range" }
    // "kind" is one of: "select" | "date-range" | "text".
    // "field" MUST be a column that exists on at least one entity
    //   backing a widget on this dashboard.
    // "options" is required for "select" and must be enum values the
    //   entity actually uses (harvested from status/type/category
    //   columns).
  ],
  "reset_filters": true
    // Include a "↺ Reset all filters" chip when there are 2+ filters.
    // Skip when 0-1 filters (no bulk-reset value).
}

STRICT RULES
1. Every `entity` value MUST be a name that appears in plan.entities.
   Do not invent entities.
2. Every `op` on numeric aggregation (`sum`/`avg`/`max`) MUST include a
   `field` that plausibly exists on the entity. Prefer common names:
   amount, price, revenue, quantity, duration, count.
3. Choose KPIs that a domain owner would actually check first thing in
   the morning. NEVER count auth/audit entities (users, sessions,
   audit_log, notification, etc.). Prefer domain-native entities.
4. The primary chart's `group_by` MUST reference either a temporal
   column (createdAt, date, week) or a categorical column with obvious
   groupings (status, category, type).
5. Choose the hero `kind` that fits the domain — a wellness studio
   deserves `editorial-quote` or `personalised-greeting` more often than
   `photo-greeting`; a fintech admin wants `kpi-strip`; a leave/credit
   dashboard wants `balance-rings`. When you do pick `photo-greeting`,
   the `photo_subject` MUST be domain-specific and evocative — "yoga
   studio interior at golden hour" not "abstract shape".
6. `signature_moves` is where per-app personality lives. 1-3 ids from
   the catalog, chosen for the domain. Two same-domain apps should pick
   distinct combinations — do not default to the same list.
7. `section_rhythm` follows the brief's personality, not the domain
   alone: a "warm, boutique" yoga studio → "generous"; a "high-density
   admin" → "tight"; a general SaaS → "cozy".
8. `subtitle`, when present, must be BRIEF-SPECIFIC prose — never
   "Dashboard" or "Overview" or the app name. It's the answer to
   "what is the reader evaluating on this page?" Skip the field
   entirely rather than emitting a generic string.
9. `filters` are OPTIONAL. Only add them when there's an obvious
   refinement question the reader would ask. Each filter's `field`
   MUST exist on at least one entity backing a widget on this page —
   filtering by a column no widget reads is dead chrome. Set
   `reset_filters: true` only when there are 2+ filters.
10. KPI `breakdown` is OPTIONAL — declare it ONLY when the primary
    value's composition matters. Good: "Clients 2,000 → Male 984 /
    Female 1,016" (the split is the story). Bad: "Queued Batches 0 →
    Q1 0 / Q2 0" (composition doesn't add signal). Two rules of thumb:
    if a domain analyst would immediately ask "how does it split?",
    add the breakdown; if the number is already a headline, don't.
    Every breakdown row's entity+field MUST plausibly exist on the
    plan (same discipline as the KPI itself).
11. KPI `threshold` is OPTIONAL — declare it ONLY for metrics where
    "high is bad" (DTI, latency, backlog, failure count). Skip for
    revenue, sign-ups, conversions where high is good. Set
    `color_on_value: true` when the metric is a headline the user
    should react to; leave false (attr-only) for background metrics.
12. KPI `extremes` is OPTIONAL — declare it ONLY on aggregated
    numeric KPIs (sum/avg over a field) where the range tells its
    own story ("$127M total spanning $5–$516K single-loan"). Skip on
    bare counts and on aggregates where max/min are meaningless.
13. Chart `overlay` is OPTIONAL — declare ONE overlay ONLY when two
    encodings together tell a single story (bars for Amount + line
    for Count over the same time axis). Do NOT overlay two random
    metrics that don't share a narrative — that produces noise.
14. Chart `view_toggles` are OPTIONAL — declare 2-3 chips ONLY when
    the reader would naturally toggle views ("Time Trend / Year Trend"
    on a transactions chart). Skip on stat-of-record charts where
    one view is authoritative.
15. Chart `encoding.leaderboard` is OPTIONAL — set to true ONLY on
    ranking screens ("top States by revenue", "worst-performing
    services"). Pair with `sorted` + `top_n`. Skip on trend charts.
16. Chart `semantic_color` is OPTIONAL — declare ONLY when the same
    categorical field appears on 2+ charts on the page AND the
    values need consistent coloring. Skip on single-chart pages.
17. Return JSON only. No prose. No markdown fences.
"""


_PERSONALITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Personality signal → list of brief keywords that trigger it. Order
    # of dict entries drives which signal wins on ties (earlier = higher
    # priority). Missing keyword sets never surface — the LLM gets the
    # raw brief text too, so this is guidance, not filtering.
    "warm / boutique / editorial": (
        "warm", "boutique", "artisan", "hand-crafted", "editorial",
        "calm", "soft", "cozy", "intimate", "considered",
    ),
    "dense / admin / efficient": (
        "dense", "admin", "efficient", "compact", "power-user",
        "utilitarian", "info-dense", "no-frills",
    ),
    "playful / consumer / bright": (
        "playful", "fun", "delightful", "bright", "vibrant",
        "consumer", "friendly", "cheerful",
    ),
    "clinical / precise / formal": (
        "clinical", "precise", "formal", "professional", "medical",
        "compliance", "audit", "authoritative",
    ),
    "modern / minimal / techy": (
        "modern", "minimal", "clean", "sleek", "geometric",
        "technical", "monospace", "grid",
    ),
}


def _extract_personality_signals(brief_text: str | None) -> list[str]:
    """Return the personality-signal labels the brief triggers.

    Deterministic keyword match against ``brief_text``. Returns [] when
    brief is empty or none of the trigger words appear. Callers surface
    the labels in the maquette user prompt so the LLM has an explicit
    personality directive alongside the raw brief text.
    """
    if not brief_text:
        return []
    haystack = brief_text.lower()
    hits: list[str] = []
    for label, triggers in _PERSONALITY_KEYWORDS.items():
        if any(kw in haystack for kw in triggers):
            hits.append(label)
    return hits


def _read_21st_references(plan: dict) -> list[str]:
    """Read cached 21st.dev component references (Angle C infrastructure).

    ``magic_prefetch`` writes per-domain reference JSON files to
    ``<output_dir>/src/contracts/references/`` before the maquette runs.
    Each file names a component (title, author, blurb) — passing the
    names to the maquette prompt lets the LLM's picks be shaped by real
    design references rather than vibes.

    Silently returns [] when the references dir doesn't exist (env flag
    off, no prefetch run) or when the plan lacks an ``_output_dir``
    (unit-test path). Never raises — a bad reference file is skipped.
    """
    if not isinstance(plan, dict):
        return []
    out_dir = plan.get("_output_dir")
    if not isinstance(out_dir, str) or not out_dir:
        return []
    ref_dir = Path(out_dir) / "src" / "contracts" / "references"
    if not ref_dir.is_dir():
        return []
    names: list[str] = []
    for ref_path in sorted(ref_dir.glob("*.json"))[:6]:
        try:
            doc = json.loads(ref_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = doc.get("name") if isinstance(doc, dict) else None
        blurb = doc.get("description") if isinstance(doc, dict) else None
        if isinstance(name, str) and name.strip():
            if isinstance(blurb, str) and blurb.strip():
                # Trim blurb — reference details are guidance not gospel.
                names.append(f"{name.strip()}: {blurb.strip()[:80]}")
            else:
                names.append(name.strip())
    return names


def _domain_dashboard_block(plan: dict) -> str:
    """The archetype vocabulary's answer to "what does someone in THIS
    business open the app to see?".

    Every other vocabulary field shaped interior list screens; the
    dashboard had no domain input at all, so an inventory app, a clinic
    and a bank all opened on the same generic KPI skeleton. This hands
    the maquette author the domain's own priorities, bound to entities
    the app actually has. Silent no-op when the archetype has no recipe
    — the author then works exactly as it did before.
    """
    try:
        from services.dashboard_vocabulary import resolve_dashboard_recipe
        from services.page_vocabulary import vocabulary_for_plan
    except Exception:  # noqa: BLE001
        return ""
    vocab = vocabulary_for_plan(plan)
    if vocab is None:
        return ""
    entity_map = plan.get("entities") or {}
    resolved = resolve_dashboard_recipe(vocab, available=list(entity_map.keys()),
                                        entities=entity_map)
    if not resolved.get("kpis") and not resolved.get("sections"):
        return ""
    lines = [
        "",
        "## WHAT THIS DOMAIN PUTS ON A DASHBOARD (authoritative)",
        f"Archetype: {getattr(vocab, 'id', '?')}. These are the metrics and",
        "working lists people in this business actually open the app for.",
        "Lead with them. You may add to them; do not replace them with",
        "generic record counts.",
    ]
    if resolved.get("kpis"):
        lines.append("KPIs, in priority order:")
        for k in resolved["kpis"]:
            filt = f" where {k['filter']}" if k.get("filter") else ""
            fld = f" of {k['field']}" if k.get("field") else ""
            lines.append(f"  - {k['label']}: {k.get('op', 'count')}{fld} "
                         f"on {k['entity']}{filt}")
    if resolved.get("sections"):
        lines.append("Body sections, in priority order:")
        for sec in resolved["sections"]:
            filt = f" where {sec['filter']}" if sec.get("filter") else ""
            lines.append(f"  - {sec['title']}: {sec['entity']}"
                         f" as {sec.get('shape', 'table')}{filt}")
    if resolved.get("empty_copy"):
        lines.append(f"Empty-state copy when there is no data yet: "
                     f"\"{resolved['empty_copy']}\"")
    return "\n".join(lines) + "\n"


def _build_user_prompt(plan: dict, brief_text: str | None) -> str:
    entities = plan.get("entities") or {}
    entity_lines: list[str] = []
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        fields = e.get("fields") or e.get("columns") or []
        field_hints: list[str] = []
        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, dict):
                    fn = f.get("name") or f.get("column")
                    ft = f.get("type") or f.get("sqlType")
                    if fn:
                        field_hints.append(f"{fn}:{ft}" if ft else str(fn))
        elif isinstance(fields, dict):
            for fn, fmeta in fields.items():
                ft = None
                if isinstance(fmeta, dict):
                    ft = fmeta.get("type") or fmeta.get("sqlType")
                field_hints.append(f"{fn}:{ft}" if ft else str(fn))
        cols_str = ", ".join(field_hints[:12]) if field_hints else "(no fields listed)"
        entity_lines.append(f"  - {name}: [{cols_str}]")

    domain = plan.get("domain") or "generic"
    module_name = plan.get("module_name") or "App"
    brief_line = f"\nUser's brief: {brief_text}\n" if brief_text else ""

    # Phase 2 additions:
    # - Personality signals: keyword-extracted labels the LLM should
    #   respect when picking hero kind, signature moves, section rhythm.
    # - Variance hint: per-brief seed so same-domain apps diverge.
    # - Design references: named 21st.dev components the LLM can use
    #   as shape inspiration.
    signals = _extract_personality_signals(brief_text)
    personality_block = ""
    if signals:
        personality_block = (
            "\nPERSONALITY SIGNALS (steer hero kind + signature moves + "
            "section rhythm toward these):\n"
            + "\n".join(f"  • {s}" for s in signals)
            + "\n"
        )

    from services.pipeline.variance import variance_hint_line
    _variance = variance_hint_line(plan)
    variance_block = f"\n{_variance}\n" if _variance else ""

    refs = _read_21st_references(plan)
    references_block = ""
    if refs:
        references_block = (
            "\nDESIGN REFERENCES (shape inspiration, not verbatim copies):\n"
            + "\n".join(f"  • {r}" for r in refs)
            + "\n"
        )

    # MONTAGE COMPOSITION. The design-reference montage says what a screen
    # of this kind carries and how dense it is — the bar this page should
    # meet. Shape only: it never names entities/columns (the plan and
    # registry below own those) and carries no colour (the picked design
    # option owns that). Empty string when no montage was designated.
    from services.montage_composition import load_composition_block
    composition_block = load_composition_block(plan)

    return f"""\
App: {module_name}
Domain: {domain}
{brief_line}{personality_block}{variance_block}{references_block}{composition_block}
Entities ({len(entities)}):
{chr(10).join(entity_lines) if entity_lines else '  (none)'}
{_domain_dashboard_block(plan)}
Emit the dashboard maquette JSON now."""


async def author_dashboard_maquette(
    plan: dict,
    *,
    brief_text: str | None = None,
    query_fn: Any | None = None,
    timeout_seconds: float = 45.0,
) -> DashboardMaquette | None:
    """Call the LLM to produce a dashboard maquette. Returns None on any
    failure. Never raises.

    Args:
        plan: The full plan dict (with entities, description, domain).
        brief_text: Original user brief text — steers content picks.
        query_fn: Injectable async ``(system, user) -> str`` for tests.
        timeout_seconds: Hard cap on the LLM call.
    """
    if not isinstance(plan, dict):
        return None
    entities = plan.get("entities")
    if not isinstance(entities, dict) or not entities:
        # No entities → no meaningful maquette. Downstream falls back.
        return None

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(plan, brief_text)

    if query_fn is not None:
        try:
            text = await query_fn(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard-maquette] injected query_fn failed: %s", exc)
            return None
    else:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            logger.warning("[dashboard-maquette] no ANTHROPIC_API_KEY; skipping")
            return None
        try:
            from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        except ImportError:
            logger.warning("[dashboard-maquette] anthropic SDK unavailable")
            return None
        try:
            client = llm_client.AsyncAnthropic(api_key=api_key)
            msg = await asyncio.wait_for(
                client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
                timeout=timeout_seconds,
            )
            text = "".join(getattr(b, "text", "") for b in msg.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard-maquette] LLM call failed: %s", exc)
            return None

    parsed = _extract_json_object(text)
    if parsed is None:
        logger.warning("[dashboard-maquette] no valid JSON in response")
        return None
    m = DashboardMaquette.from_dict(parsed)

    # Sanity: every referenced entity must exist in the plan. Drop
    # references that don't.
    entity_names_lower = {n.lower() for n in entities.keys()}
    m.kpis = [k for k in m.kpis if k.entity.lower() in entity_names_lower]
    if m.primary_chart and m.primary_chart.entity.lower() not in entity_names_lower:
        m.primary_chart = None
    if m.activity and m.activity.entity.lower() not in entity_names_lower:
        m.activity = None
    return m


def _extract_json_object(text: str) -> dict | None:
    """Balance-scan the first {...} in ``text``. Handles markdown fences."""
    if not text:
        return None
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
