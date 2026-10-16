"""A page Smith changes or adds is written for the phone too, to the same words.

A native application has one screen per page. Smith edits the web page; without this the phone's screen kept the
old one and the two drifted apart after every change. The native screen is written beside the web code and
lands in the same version; when it cannot be written the web change still stands and the person is told."""
from __future__ import annotations

import inspect

import pytest

from services.blueprint import native_engineer
from services.blueprint.ui_engineer import CompileError, NeedsWorkflow
from services.smith import compose

PAGE = {"id": "PAGE-002", "name": "Appointments", "route": "/appointments", "pattern": "entity_list", "access": "authenticated"}


class Svc:
    output_dir = "/tmp/nowhere"


def doc(native: bool = True, rows: list[dict] | None = None, pages: list[dict] | None = None) -> dict:
    return {"application": {"name": "Paws"}, "mobile": {"native": {"enabled": native}}, "pages": pages or [PAGE],
            "nativeCode": rows if rows is not None else [{"page": "PAGE-002", "screen": "old screen"}]}


@pytest.fixture
def router(monkeypatch):
    class _Router:
        def for_task(self, node, agent):
            assert (node, agent) == ("native_code", "native_engineer")
            return "the-native-model"

    monkeypatch.setattr("services.blueprint.executors.tiered_router", lambda reasoning=None: _Router())


def test_an_app_that_is_not_native_has_nothing_written_for_the_phone(monkeypatch):
    monkeypatch.setattr(native_engineer, "compose_screen", lambda *a, **k: pytest.fail("not native: nothing to write"))
    assert compose.native_follow(Svc(), doc(native=False), PAGE, brief="x") == (None, "")


def test_a_page_with_no_phone_screen_is_left_alone(monkeypatch):
    monkeypatch.setattr(native_engineer, "compose_screen", lambda *a, **k: pytest.fail("no screen for an audit trail"))
    audit = {**PAGE, "id": "PAGE-009", "pattern": "audit_trail"}
    assert compose.native_follow(Svc(), doc(pages=[audit]), audit, brief="x") == (None, "")


def test_the_screen_is_written_to_the_same_words_and_from_its_current_version(monkeypatch, router):
    seen = {}

    def fake(d, page, root, client, **kw):
        seen.update(kw, client=client, page=page["id"])
        return {"page": page["id"], "screen": "new screen", "rationale": "r"}, []

    monkeypatch.setattr(native_engineer, "compose_screen", fake)
    body, note = compose.native_follow(Svc(), doc(), PAGE, brief="Show the vet on each row")
    assert body["screen"] == "new screen" and note == ""
    assert seen["brief"] == "Show the vet on each row" and seen["current"] == {"page": "PAGE-002", "screen": "old screen"}
    assert seen["client"] == "the-native-model" and seen["node"] == "native_code"


def test_a_new_page_is_written_from_nothing(monkeypatch, router):
    seen = {}
    monkeypatch.setattr(native_engineer, "compose_screen",
                        lambda d, p, r, c, **kw: (seen.update(kw) or {"page": p["id"], "screen": "s"}, []))
    compose.native_follow(Svc(), doc(rows=[]), PAGE, brief="A page of stock")
    assert seen["current"] is None


@pytest.mark.parametrize("error, said", [
    (CompileError("PAGE-002: still does not compile"), "did not compile"),
    (NeedsWorkflow(["delete an owner"]), "no workflow makes"),
    (RuntimeError("no model"), "could not be written"),
])
def test_a_screen_that_cannot_be_written_is_said_and_never_stops_the_web_change(monkeypatch, router, error, said):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(native_engineer, "compose_screen", fail)
    body, note = compose.native_follow(Svc(), doc(), PAGE, brief="x")
    assert body is None and said in note


def test_every_smith_change_to_a_coded_page_goes_through_the_hook():
    """`recode_page` is the one place the web page is rewritten (edit, add, field and entity changes all call it)."""
    source = inspect.getsource(compose.recode_page)
    assert "native_follow(" in source and 'section="nativeCode"' in source
    assert "one undo" in source.lower() or "SAME version" in source, "the phone's screen lands in the web change's version"
