"""The look of the application is a Blueprint section, and Smith can change it.

"Change the theme colour from blue to green" was answered with "I looked for
'Soft Care — white and muted lavender-blue…' in /nurse-registration and could
not find it": the palette was in every slice Smith read and no move touched
`designSystem`, so the ask was squeezed into a rename. A restyle records the
decision, re-runs the design agent against a brief, commits through the
Blueprint and re-projects the tokens — no page is re-composed."""

import copy
import json

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.service import BlueprintService
from services.smith import restyle as rs

LAVENDER = {
    "accent": "#D9A441", "background": "#FFFFFF", "border": "#E2E5F5", "error": "#C1443C",
    "info": "#3B6FB6", "primary": "#6E7FDB", "primary-hover": "#5A6BC4", "primary-subtle": "#EEF0FC",
    "success": "#2E7D5B", "surface": "#F7F8FC", "text-primary": "#2B2D42",
    "text-secondary": "#6B6F8C", "warning": "#B8860B",
}
GREEN = {**LAVENDER, "primary": "#2E7D5B", "primary-hover": "#256647", "primary-subtle": "#EAF4EE",
         "accent": "#C86B3C", "border": "#DCE7E0", "surface": "#F5F9F6"}


def _design(colors):
    return {
        "colors": dict(colors),
        "borders": {"color-default": colors["border"], "style-default": "solid", "width-default": "1px"},
        "radius": {"full": "9999px", "lg": "12px", "md": "8px", "sm": "4px"},
        "spacing": {"lg": "24px", "md": "16px", "sm": "8px", "xs": "4px"},
        "elevation": {"none": "none", "sm": "0 1px 2px rgba(43,45,66,0.06)"},
        "informationDensity": "comfortable",
        "navigationApproach": "Flat sidebar with two entries.",
        "visualPersonality": "Soft Care: colour source is the application description, "
                             "'white and muted lavender-blue'.",
        "accessibilityRules": ["Keyboard reachable"],
        "interactionConventions": ["Primary actions use the primary colour"],
        "responsiveRules": ["Sidebar collapses below 640px"],
        "derivedFromFigma": False,
    }


@pytest.fixture(autouse=True)
def _unscoped(monkeypatch):
    """The small model that reads which roles a request names is not called in
    these tests; "could not tell" is the unscoped behaviour they were written for."""
    monkeypatch.setattr(rs, "roles_named", lambda change, roles: None)


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["designSystem"] = _design(LAVENDER)
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Register nurses."}]
    s.upsert("decisions", {"decision": "Soft Care — white and muted lavender-blue, calm and approachable",
                           "reason": "In discovery, asked: Which colour palette fits this app best?",
                           "source": "user", "approvedBy": "user", "binding": True,
                           "status": "APPROVED", "version": 1}, natural_key="REQ-001")
    s.save()
    (tmp_path / "app" / "src" / "app").mkdir(parents=True)
    return s


def _executor(seen, colors=GREEN):
    def run(spec):
        seen.append(spec)
        body = _design(colors)
        body["visualPersonality"] = "Colour now comes from the restyle decision: green."
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="designSystem", natural_key="designSystem", body=body)])
    return run


def test_a_restyle_is_a_decision_a_rerun_of_the_design_agent_and_new_tokens(svc, tmp_path):
    seen = []
    out = rs.restyle(svc, "change the theme colour from blue to green",
                     app_root=str(tmp_path / "app"), executor=_executor(seen))
    # the design agent, the same node the build runs, briefed on what changed and what to keep
    assert [s.node for s in seen] == ["design_system"]
    brief = seen[0].brief
    assert "change the theme colour from blue to green" in brief
    assert "STANDING RULE ABOUT COLOUR SOURCE IS SUPERSEDED" in brief and "lavender-blue" in brief
    assert "Keep the SAME colour role names" in brief and '"primary": "#6E7FDB"' in brief
    # the Blueprint: new colours, a decision that supersedes the palette decision
    assert out["applied"] and out["after"]["primary"] == "#2E7D5B"
    assert out["changed"]["primary"] == ("#6E7FDB", "#2E7D5B") and "surface" in out["changed"]
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    assert fresh.doc["designSystem"]["colors"]["primary"] == "#2E7D5B"
    assert fresh.doc["designSystem"]["radius"]["md"] == "8px"           # untouched decisions kept
    decisions = {d["id"]: d for d in fresh.doc["decisions"]}
    new = decisions[out["decision"]]
    assert new["decision"] == "change the theme colour from blue to green" and new["binding"]
    assert new["supersedes"] == out["supersedes"] and decisions[out["supersedes"]]["decision"].startswith("Soft Care")
    # the tokens: re-projected, no page re-composed
    assert out["edited_paths"] == ["src/app/tokens.css"]
    css = (tmp_path / "app" / "src" / "app" / "tokens.css").read_text()
    primary = next(l for l in css.splitlines() if l.strip().startswith("--primary:"))
    assert "231 60% 65%" not in primary                                     # lavender's HSL is gone
    assert "--primary-hover: #256647" in css and "#5A6BC4" not in css       # roles written verbatim
    assert fresh.doc.get("pageLayouts", []) == []                         # nothing composed


def test_a_refused_design_system_is_asked_again_with_the_reason(svc, tmp_path, monkeypatch):
    seen = []
    from services.smith import change as ch
    real = ch.apply_change
    calls = {"n": 0}
    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            from services.blueprint.service import BlueprintInvalid
            raise BlueprintInvalid(["colors.primary: not a hex colour"])
        return real(*a, **kw)
    monkeypatch.setattr(ch, "apply_change", flaky)
    out = rs.restyle(svc, "green theme", app_root=str(tmp_path / "app"), executor=_executor(seen))
    assert out["applied"] and [s.attempt for s in seen] == [1, 2]
    assert "not a hex colour" in seen[1].feedback and seen[1].brief == seen[0].brief


def test_nothing_to_restyle_is_said_not_crashed(tmp_path, svc):
    assert rs.run(str(tmp_path / "nowhere"), "green")["applied"] is False
    svc.doc["designSystem"] = {}
    svc.save()
    with pytest.raises(rs.RestyleError, match="no design system yet"):
        rs.restyle(svc, "green", executor=_executor([]))
    with pytest.raises(rs.RestyleError, match="nothing to restyle"):
        rs.restyle(svc, "   ", executor=_executor([]))


def test_the_summary_says_what_moved(svc, tmp_path):
    out = rs.restyle(svc, "green theme", app_root=str(tmp_path / "app"), executor=_executor([]))
    text = rs.summary_of(out, "green theme")
    assert "primary #6E7FDB → #2E7D5B" in text and out["decision"] in text and out["supersedes"] in text
    assert "without being re-composed" in text


# --- the two entry points share it ---------------------------------------------


def test_a_palette_returned_unchanged_is_refused_and_records_no_decision(svc, tmp_path):
    """Live, the agent read "use the colour the description names" over the
    brief, returned lavender-blue, and the seam reported "Restyled: 0 colour
    role(s)" with a decision recorded over a palette that ignored it."""
    seen = []
    with pytest.raises(rs.RestyleError, match="kept the palette unchanged 2 times"):
        rs.restyle(svc, "green theme", app_root=str(tmp_path / "app"), executor=_executor(seen, colors=LAVENDER))
    assert [s.attempt for s in seen] == [1, 2]
    assert "came back exactly as it was" in seen[1].feedback
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    assert fresh.doc["designSystem"]["colors"]["primary"] == "#6E7FDB"
    assert all(d["decision"] != "green theme" for d in fresh.doc["decisions"])   # nothing recorded
    assert not (tmp_path / "app" / "src" / "app" / "tokens.css").exists()


def test_an_unchanged_first_attempt_can_still_succeed_on_the_second(svc, tmp_path):
    calls = {"n": 0}
    def flaky(spec):
        calls["n"] += 1
        return _executor([], colors=LAVENDER if calls["n"] == 1 else GREEN)(spec)
    out = rs.restyle(svc, "green theme", app_root=str(tmp_path / "app"), executor=flaky)
    assert out["applied"] and out["after"]["primary"] == "#2E7D5B" and calls["n"] == 2


# --------------------------------------------------------------------------- #
# One role asked for is one role changed (Mark 8, cxz95dd1, 2026-10-16)
# --------------------------------------------------------------------------- #

WHITE_EVERYTHING = {**GREEN, "background": "#FFFDF9", "text-primary": "#1A1D21", "surface": "#F6F1E6"}


def test_the_scope_of_a_request_is_the_roles_it_names_and_their_dependants():
    roles = sorted(LAVENDER)
    assert rs.scope_of(["primary"], roles) == {"primary", "primary-hover", "primary-subtle"}
    assert rs.scope_of(["background"], roles) == {"background", "text-primary", "text-secondary", "border"}
    assert rs.scope_of(["accent"], roles) == {"accent"}
    assert rs.scope_of([rs.ALL_ROLES], roles) is None and rs.scope_of(None, roles) is None
    colors, kept = rs.kept_in_scope(LAVENDER, WHITE_EVERYTHING, rs.scope_of(["background"], roles))
    assert colors["background"] == "#FFFDF9" and colors["text-primary"] == "#1A1D21" and colors["border"] == GREEN["border"]
    assert colors["primary"] == LAVENDER["primary"] and colors["accent"] == LAVENDER["accent"]
    assert kept == ["accent", "primary", "primary-hover", "primary-subtle", "surface"]


def test_a_request_for_the_background_changes_the_background_and_keeps_the_rest(svc, tmp_path, monkeypatch):
    """"Change the background colour to white" came back with a new accent, a
    new primary and fourteen more roles: the agent re-derived a scheme. The
    agent's answer is held to the role the request names."""
    monkeypatch.setattr(rs, "roles_named", lambda change, roles: ["background"])
    seen = []
    out = rs.restyle(svc, "change the background colour to white", app_root=str(tmp_path / "app"),
                     executor=_executor(seen, colors=WHITE_EVERYTHING))
    assert "THE REQUEST NAMES: background. Change that role and nothing else." in seen[0].brief
    assert out["after"]["background"] == "#FFFDF9" and out["after"]["text-primary"] == "#1A1D21"
    assert out["after"]["primary"] == LAVENDER["primary"] and out["after"]["accent"] == LAVENDER["accent"]
    # The border sits on the background, so it may follow it; the accent and the primary may not.
    assert set(out["changed"]) == {"background", "text-primary", "border"}
    assert out["kept"] == ["accent", "primary", "primary-hover", "primary-subtle", "surface"]
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    assert fresh.doc["designSystem"]["colors"]["accent"] == LAVENDER["accent"]
    text = rs.summary_of(out, "change the background colour to white")
    assert "background #FFFFFF → #FFFDF9" in text and "every other role kept as it was" in text
    assert "accent" in text and "14 more" not in text


def test_a_request_about_the_whole_palette_still_re_derives_the_scheme(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "roles_named", lambda change, roles: [rs.ALL_ROLES])
    seen = []
    out = rs.restyle(svc, "a green theme", app_root=str(tmp_path / "app"), executor=_executor(seen))
    assert "THE REQUEST NAMES" not in seen[0].brief and "re-derive primary-hover" in seen[0].brief
    assert out["kept"] == [] and out["after"]["accent"] == GREEN["accent"]


def test_an_agent_that_changed_only_what_was_not_asked_is_asked_again(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "roles_named", lambda change, roles: ["background"])
    calls = {"n": 0}

    off_scope = {**LAVENDER, "accent": GREEN["accent"], "primary": GREEN["primary"]}

    def flaky(spec):
        calls["n"] += 1
        # First answer: a new accent and primary, the background untouched — nothing in scope changed.
        return _executor([], colors=off_scope if calls["n"] == 1 else WHITE_EVERYTHING)(spec)
    out = rs.restyle(svc, "change the background colour to white", app_root=str(tmp_path / "app"), executor=flaky)
    assert calls["n"] == 2 and out["after"]["background"] == "#FFFDF9" and out["after"]["accent"] == LAVENDER["accent"]
