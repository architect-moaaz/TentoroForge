""""Specification", said in answer to Smith's own question, pulls the design in.

On forge-v3 (Tentoro, 2026-10-22) Smith asked "is this design the SPECIFICATION
or a REFERENCE?", the person answered "Specification" four times, and was asked
four times. The loop re-ran `connect_figma` with the link and the variable name
and nothing else: the scope was read only from the call's own fields, and the
catalogue never listed that field, so the answer had nowhere to arrive.
"""
from __future__ import annotations

import pytest

from services.smith import tools
from services.smith.understand_ask import _design_scope

URL = "https://www.figma.com/design/5zFDI0TaWGryb2DZAde11l/Tentoro?node-id=4263-1934"
CALL = {"tool": "connect_figma", "args": {"figma_url": URL, "token_env": "FIGMA_ACCESS_TOKEN"}, "why": "pull it in"}


@pytest.mark.parametrize("said,scope", [
    ("Specification", "specification"), ("specification.", "specification"), ("spec", "specification"),
    ("Reference", "evidence"), ("the reference!", "evidence"),
    ("build exactly what I drew", ""), ("", ""),
])
def test_the_two_words_the_question_offers_are_the_words_it_hears(said, scope):
    assert _design_scope(said) == scope


def test_the_model_is_told_the_verb_takes_the_answer():
    line = next(l for l in tools.render().splitlines() if l.startswith("- `connect_figma`"))
    assert "treat_as?: specification | reference" in line
    line = next(l for l in tools.render().splitlines() if l.startswith("- `connect_uxpilot`"))
    assert "treat_as?:" in line


@pytest.fixture()
def connected(monkeypatch):
    calls: list[dict] = []

    def connect(output_dir, *, figma_url, token_env, treat_as):
        calls.append({"figma_url": figma_url, "token_env": token_env, "treat_as": treat_as})
        return {"summary": f"Pulled in 6 frames as the {treat_as}."}
    monkeypatch.setattr("services.smith.figma_connect.connect", connect)
    return calls


def test_the_answer_typed_after_the_question_pulls_the_design_in(tmp_path, connected):
    from services.smith4 import handle
    from tests.services._loop_fixtures import _Chooser, _repo, _Writes

    _repo(tmp_path)
    ask = f"can you observe this figma design {URL} and convert the design and process"
    first = handle(project_id="p1", output_dir=str(tmp_path), message=ask, move=_Writes(tmp_path),
                   choose=_Chooser(CALL))
    assert first.status == "asked" and "SPECIFICATION or a REFERENCE" in first.said
    assert first.options == ["Specification", "Reference"] and not connected

    # What the loop did on forge-v3: the same call again, without the answer.
    second = handle(project_id="p1", output_dir=str(tmp_path), message="Specification",
                    history=[("user", ask), ("smith", first.said)], move=_Writes(tmp_path),
                    choose=_Chooser(CALL, {"tool": "done", "args": {}, "why": ""}))
    assert connected == [{"figma_url": URL, "token_env": "FIGMA_ACCESS_TOKEN", "treat_as": "specification"}]
    assert "SPECIFICATION or a REFERENCE" not in second.said
    assert "Pulled in 6 frames as the specification." in second.said


def test_a_scope_the_call_carries_is_used_as_it_is(tmp_path, connected):
    from services.smith4.verbs import Ctx, connect_figma

    out = connect_figma(Ctx(output_dir=str(tmp_path), project_id="p", message="go on", ask=""),
                        {"verb": "connect_figma", "figma_url": URL, "token_env": "FIGMA_ACCESS_TOKEN",
                         "treat_as": "reference"})
    assert out.status == "resolved" and connected[-1]["treat_as"] == "evidence"


def test_anything_else_is_still_asked(tmp_path, connected):
    from services.smith4.verbs import Ctx, connect_figma

    out = connect_figma(Ctx(output_dir=str(tmp_path), project_id="p", message="yes do it", ask=""),
                        {"verb": "connect_figma", "figma_url": URL, "token_env": "FIGMA_ACCESS_TOKEN"})
    assert out.status == "asked" and not connected


def test_ux_pilot_hears_the_answer_the_same_way(tmp_path, monkeypatch):
    from services.smith4.verbs import Ctx, connect_uxpilot

    seen: list[str] = []
    monkeypatch.setattr("services.smith.uxpilot_connect.connect",
                        lambda out, *, uxpilot_ref, key_env, treat_as: seen.append(treat_as) or {"summary": "ok"})
    monkeypatch.setattr("services.uxpilot.url.parse", lambda ref: ref)
    out = connect_uxpilot(Ctx(output_dir=str(tmp_path), project_id="p", message="Reference", ask=""),
                          {"verb": "connect_uxpilot", "uxpilot_ref": "page-123", "key_env": "UXPILOT_API_KEY"})
    assert out.status == "resolved" and seen == ["evidence"]
