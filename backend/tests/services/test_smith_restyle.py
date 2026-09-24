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

def test_the_verb_and_the_tool_both_reach_the_one_implementation(monkeypatch, tmp_path):
    import services.smith_tools as smith_tools
    from services.smith.verbs import REQUIRED_BY_VERB, missing_fields
    from services.smith.tools import render as _catalogue
    assert REQUIRED_BY_VERB["restyle"] == {"change"} and "`restyle`" in _catalogue() and "`restyle` (" in _catalogue()
    assert missing_fields({"verb": "restyle"}) == ["change"]
    entry = next(t for t in smith_tools.TOOL_CATALOG if t["name"] == "restyle")
    assert "edit_page" in entry["desc"] and "restyle" in smith_tools.READONLY_HANDLERS
    assert smith_tools.READONLY_HANDLERS["restyle"](str(tmp_path), {})["applied"] is False
    called = []
    monkeypatch.setattr("services.smith.restyle.run",
                        lambda output_dir, change, **kw: called.append(change) or
                        {"applied": True, "edited_paths": ["src/app/tokens.css"], "diff_summary": "Restyled."})
    assert smith_tools.READONLY_HANDLERS["restyle"](str(tmp_path), {"change": "green"})["applied"]
    from tests.services._front_door import SmithSession
    session = SmithSession(project_id="p1", output_dir=str(tmp_path), guards_fn=lambda _d: [],
                           understand_ask_fn=lambda m, c, history=None: {"verb": "restyle", "change": "green theme"},
                           iteration_move_fn=lambda *a, **k: None)
    result = session.run_iteration(user_message="change the theme colour to green")
    assert result.status == "resolved" and result.touched_paths == ["src/app/tokens.css"]
    assert called == ["green", "green theme"]



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
