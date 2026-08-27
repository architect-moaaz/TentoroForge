"""Enum inference: well-known small-value-set fields (status/priority/stage) with no
registry enum_values and no harvestable workflow literals still become a Select via a
conservative curated dictionary — while open-ended fields (nationality/notes/title) and
FK columns stay a plain Input. Value precedence: real declared/harvested options always
win over the curated fallback."""
from services.semantic_field_types import _decide, curated_enum_options


# --- curated dictionary → Select --------------------------------------------------

def test_priority_varchar_becomes_curated_select():
    kind, extra = _decide("priority", "varchar", None)
    assert kind == "Select"
    assert {o["value"] for o in extra["options"]} == {"Low", "Medium", "High", "Urgent"}


def test_status_varchar_becomes_curated_select():
    kind, extra = _decide("status", "varchar", None)
    assert kind == "Select"
    assert "Active" in {o["value"] for o in extra["options"]}


def test_stage_last_token_match_becomes_select():
    # matched on the LAST word token, so compound names still hit
    assert _decide("currentStage", "varchar", None)[0] == "Select"
    assert _decide("pipelineStage", "", None)[0] == "Select"


# --- open-ended / FK fields stay Input --------------------------------------------

def test_nationality_stays_input():
    assert _decide("nationality", "varchar", None)[0] != "Select"


def test_title_and_notes_stay_non_select():
    assert _decide("title", "varchar", None)[0] != "Select"
    # notes is a text column → Textarea, never a curated Select
    assert _decide("notes", "text", None)[0] != "Select"


def test_fk_column_never_curated():
    # candidateId is a FK — left for the relational builder, never a curated Select
    assert _decide("candidateId", "varchar", None)[0] is None
    assert curated_enum_options("candidateId") is None


def test_statusreport_last_token_not_curated():
    # last token "report" (not "status") → free text, not a status enum
    assert curated_enum_options("statusReport") is None
    assert _decide("statusReport", "varchar", None)[0] != "Select"


# --- precedence + type-safety -----------------------------------------------------

def test_real_options_win_over_curated():
    kind, extra = _decide("status", "varchar", ["Applied", "Screening", "Offer"])
    assert kind == "Select"
    assert [o["value"] for o in extra["options"]] == ["Applied", "Screening", "Offer"]


def test_numeric_priority_is_number_not_curated_select():
    # a priority typed as an integer is a stepper, not a curated Low/Medium/High Select
    assert _decide("priority", "integer", None)[0] == "NumberInput"
