"""Page-polish helpers — the 4 levers that let the deterministic builders
produce richer output without dropping the planner's IA taste."""
from __future__ import annotations

import pytest

from services.page_polish import (
    compose_card_actions,
    compose_features,
    compose_header_actions,
    parse_description_hints,
    pick_card_props,
)


# --------------------------------------------------------------------------- #
# Fixtures — representative Candidate + Application-ish column dicts
# --------------------------------------------------------------------------- #

CANDIDATE_COLS_WITH_FULLNAME = {
    "id":             {"type": "uuid", "primaryKey": True},
    "fullName":       {"type": "varchar", "notNull": True},
    "email":          {"type": "varchar", "notNull": True},
    "nationality":    {"type": "varchar"},
    "avatarUrl":      {"type": "text"},
    "status":         {"type": "varchar",
                        "enum": ["Applied", "Screening", "Shortlisted",
                                 "Interviewing", "Offered", "Rejected"]},
    "experienceLevel":{"type": "varchar", "enum": ["Junior", "Mid", "Senior"]},
    "driveId":        {"type": "uuid"},          # FK
    "createdAt":      {"type": "timestamp"},
}

CANDIDATE_COLS_COMPOSITE = {
    "id":         {"type": "uuid", "primaryKey": True},
    "firstName":  {"type": "varchar", "notNull": True},
    "lastName":   {"type": "varchar", "notNull": True},
    "email":      {"type": "varchar"},
    "status":     {"type": "varchar", "enum": ["Applied", "Shortlisted"]},
    "createdAt":  {"type": "timestamp"},
}

CANDIDATE_COLS_EMAIL_ONLY = {
    "id":        {"type": "uuid", "primaryKey": True},
    "email":     {"type": "varchar", "notNull": True},
    "status":    {"type": "varchar", "enum": ["Applied", "Rejected"]},
    "createdAt": {"type": "timestamp"},
}


# =========================================================================
# Lever 1 — pick_card_props
# =========================================================================

def test_pick_card_props_prefers_fullname_over_email():
    props = pick_card_props(CANDIDATE_COLS_WITH_FULLNAME)
    assert props["cardTitle"] == "fullName"


def test_pick_card_props_picks_subtitle_from_role_family():
    props = pick_card_props(CANDIDATE_COLS_WITH_FULLNAME)
    assert props.get("cardSubtitle") == "nationality"


def test_pick_card_props_detects_avatar_column():
    props = pick_card_props(CANDIDATE_COLS_WITH_FULLNAME)
    assert props.get("cardImage") == "avatarUrl"


def test_pick_card_props_uses_composite_name_when_no_fullname():
    """firstName + lastName → concat binding, NOT just email."""
    props = pick_card_props(CANDIDATE_COLS_COMPOSITE)
    assert props["cardTitle"] == "{{firstName}} {{lastName}}"


def test_pick_card_props_falls_back_to_email_when_only_option():
    """Old behaviour still holds when the entity really has nothing better."""
    props = pick_card_props(CANDIDATE_COLS_EMAIL_ONLY)
    assert props["cardTitle"] == "email"


def test_pick_card_props_honors_description_hints_for_title():
    """When the description parser surfaces 'title=nationality', honor it
    over the default fullName priority — the planner knew what it wanted."""
    props = pick_card_props(
        CANDIDATE_COLS_WITH_FULLNAME,
        hints={"title": "nationality"},
    )
    assert props["cardTitle"] == "nationality"


def test_pick_card_props_drops_hints_that_dont_match_real_columns():
    """Planner said 'cards show gender' but there is no gender column
    → fall through to the default picking rules, don't emit garbage."""
    props = pick_card_props(
        CANDIDATE_COLS_WITH_FULLNAME,
        hints={"title": "gender"},
    )
    assert props["cardTitle"] == "fullName"


def test_pick_card_props_hint_badges_deduplicate():
    props = pick_card_props(
        CANDIDATE_COLS_WITH_FULLNAME,
        hints={"badges": ["status", "status", "experienceLevel"]},
    )
    assert props["cardBadges"] == ["status", "experienceLevel"]


def test_pick_card_props_default_badges_prefers_status():
    props = pick_card_props(CANDIDATE_COLS_WITH_FULLNAME)
    assert props.get("cardBadges") == ["status"]


# =========================================================================
# Lever 2 — compose_card_actions / compose_header_actions
# =========================================================================

_PLANNER_ROW_ACTIONS = [
    {"kind": "row_action", "label": "Shortlist",
     "workflow": "CandidatePipelineWorkflow",
     "input_map": {"status": "'Shortlisted'"}, "requires_record": True},
    {"kind": "row_action", "label": "Reject",
     "workflow": "CandidatePipelineWorkflow",
     "input_map": {"status": "'Rejected'"}, "requires_record": True},
]


def test_compose_card_actions_preserves_workflow_and_inputs():
    out = compose_card_actions(_PLANNER_ROW_ACTIONS)
    assert len(out) == 2
    assert out[0] == {"label": "Shortlist",
                       "workflow": "CandidatePipelineWorkflow",
                       "input_map": {"status": "'Shortlisted'"}}
    assert out[1]["label"] == "Reject"


def test_compose_card_actions_ignores_collection_actions():
    """Header-level actions belong on compose_header_actions, not the card."""
    actions = [
        {"kind": "collection_action", "label": "Export"},
        {"kind": "row_action", "label": "Approve", "workflow": "X"},
    ]
    out = compose_card_actions(actions)
    labels = [a["label"] for a in out]
    assert labels == ["Approve"]


def test_compose_card_actions_drops_malformed_entries():
    out = compose_card_actions([
        {"kind": "row_action"},                    # no label
        "not-a-dict",                              # bad shape
        {"kind": "row_action", "label": ""},       # empty label
        {"kind": "row_action", "label": "Ok"},     # valid
    ])
    assert len(out) == 1 and out[0]["label"] == "Ok"


def test_compose_header_actions_picks_up_collection_actions():
    actions = [
        {"kind": "collection_action", "label": "Add candidate", "navigate": "/candidates/new"},
        {"kind": "row_action", "label": "Ignored"},
    ]
    out = compose_header_actions(actions)
    assert len(out) == 1
    assert out[0]["label"] == "Add candidate"
    assert out[0]["navigate"] == "/candidates/new"


def test_missing_kind_defaults_to_row_action():
    """Historical planner output sometimes omits `kind`; treat as row_action."""
    out = compose_card_actions([{"label": "Advance", "workflow": "W"}])
    assert len(out) == 1 and out[0]["label"] == "Advance"


# =========================================================================
# Lever 3 — feature composers
# =========================================================================

def test_compose_features_approval_adds_approve_reject_actions():
    r = compose_features(
        ["approval"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    actions = r["extra_card_props"].get("cardActions") or []
    labels = [a["label"] for a in actions]
    assert "Approve" in labels and "Reject" in labels
    # And the approve action binds status='Approved'.
    approve = next(a for a in actions if a["label"] == "Approve")
    assert approve["input_map"] == {"status": "'Approved'"}


def test_compose_features_filterable_emits_chip_row_from_enum_and_fk():
    r = compose_features(
        ["filterable"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    row = next(iter(r["header_nodes"]), None)
    assert row is not None and row["type"] == "Row"
    chip_fields = [c["props"]["field"] for c in row["children"]]
    # Includes an enum column ('status') AND the FK column ('driveId').
    assert "status" in chip_fields
    assert "driveId" in chip_fields


def test_compose_features_metrics_emits_stat_row_and_data_sources():
    r = compose_features(
        ["metrics"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    row = next((n for n in r["header_nodes"] if n["type"] == "Row"), None)
    assert row is not None
    stat_labels = [c["props"]["label"] for c in row["children"] if c["type"] == "Stat"]
    assert any("Total Candidates" in l for l in stat_labels)
    # DataSources include the total count.
    ds_names = [d["name"] for d in r["extra_ds"]]
    assert "candidatesCount" in ds_names
    # Per-status counts up to 3.
    per_status = [d for d in r["extra_ds"] if "op" in d and d["op"] == "count" and d.get("where")]
    assert 1 <= len(per_status) <= 3


def test_compose_features_timeline_appends_recent_card():
    r = compose_features(
        ["timeline"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    footer = r["footer_nodes"]
    assert footer, "timeline feature should add a footer node"
    card = footer[0]
    assert card["type"] == "Card"
    inner = card["children"][0]
    assert inner["type"] == "Timeline"
    # Recent-events dataSource added, ordered by createdAt desc.
    ds = next(d for d in r["extra_ds"] if d["name"] == "candidatesRecent")
    assert ds["op"] == "list"
    assert ds["orderBy"] == "createdAt"
    assert ds["orderDir"] == "desc"


def test_compose_features_search_emits_search_input_at_top_of_header():
    r = compose_features(
        ["search"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    assert r["header_nodes"]
    search = r["header_nodes"][0]
    assert search["type"] == "Input"
    assert search["props"]["type"] == "search"


def test_compose_features_composes_multiple_features():
    r = compose_features(
        ["approval", "filterable", "metrics", "timeline", "search"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    header_types = [n["type"] for n in r["header_nodes"]]
    # Search always first (inserted at 0), then filter chips, then metrics row.
    assert header_types[0] == "Input"
    assert "Row" in header_types
    # Approval adds cardActions.
    assert r["extra_card_props"].get("cardActions")
    # Timeline in footer.
    assert r["footer_nodes"]


def test_compose_features_unknown_feature_is_ignored():
    r = compose_features(
        ["not-a-real-feature", "search"],
        columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate",
        data_source="candidates",
    )
    # Search still fires; unknown one is silently ignored.
    assert r["header_nodes"]


def test_compose_features_underscore_and_hyphen_are_equivalent():
    r_hyphen = compose_features(
        ["status-pipeline"], columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate", data_source="candidates",
    )
    r_under = compose_features(
        ["status_pipeline"], columns=CANDIDATE_COLS_WITH_FULLNAME,
        entity="Candidate", data_source="candidates",
    )
    # Both normalize; nothing crashes on either shape.
    assert r_hyphen and r_under


# =========================================================================
# Lever 4 — parse_description_hints
# =========================================================================

_KANBAN_DESCRIPTION = (
    "Kanban board of candidates grouped by pipeline status: Applied, Screening, "
    "Shortlisted, Interview Scheduled, Offered, Rejected. Cards show name, "
    "nationality, and aviation experience badge."
)


def test_parse_description_extracts_shown_columns_as_title_subtitle_badges():
    hints = parse_description_hints(_KANBAN_DESCRIPTION, CANDIDATE_COLS_WITH_FULLNAME)
    # "name" doesn't map (no `name` column) → skip; "nationality" is real.
    # "aviation experience badge" → "experience" → experienceLevel.
    assert hints.get("subtitle") in ("nationality",) or hints.get("title") == "nationality"
    assert hints.get("badges") == ["experienceLevel"] or "experienceLevel" in (hints.get("badges") or [])


def test_parse_description_extracts_group_by():
    hints = parse_description_hints(_KANBAN_DESCRIPTION, CANDIDATE_COLS_WITH_FULLNAME)
    assert hints.get("groupBy") == "status"


def test_parse_description_extracts_filter_columns():
    desc = "List of applications you can filter by drive and status."
    cols = {"drive":   {"type": "varchar"},
             "status":  {"type": "varchar", "enum": ["A", "B"]},
             "createdAt": {"type": "timestamp"}}
    hints = parse_description_hints(desc, cols)
    assert hints.get("filters") == ["drive", "status"]


def test_parse_description_ignores_phrases_that_dont_match_columns():
    desc = "Show cards with quantum flux + entanglement level."
    hints = parse_description_hints(desc, CANDIDATE_COLS_WITH_FULLNAME)
    # No column matches → no hint keys set.
    assert hints == {}


def test_parse_description_returns_empty_for_missing_input():
    assert parse_description_hints("", CANDIDATE_COLS_WITH_FULLNAME) == {}
    assert parse_description_hints(None, CANDIDATE_COLS_WITH_FULLNAME) == {}


# =========================================================================
# Cross-lever integration — description hints flow into card picking
# =========================================================================

def test_end_to_end_description_hint_influences_card_props():
    hints = parse_description_hints(_KANBAN_DESCRIPTION, CANDIDATE_COLS_WITH_FULLNAME)
    props = pick_card_props(CANDIDATE_COLS_WITH_FULLNAME, hints=hints)
    # cardTitle default = fullName (still); subtitle honors the hint.
    assert props["cardTitle"] == "fullName"
    # Badge from description hint honored.
    assert "experienceLevel" in (props.get("cardBadges") or [])
