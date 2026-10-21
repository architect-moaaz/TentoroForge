"""An API manual sent first and a BRD after are both used.

A document was stored only by the turn that wrote the definition, so one
attached to a turn Smith answered with a question was gone by the next, and
the app was defined from the BRD alone (2026-10-20)."""
from __future__ import annotations

import inspect

from routers import blueprint_generate as bg
from services.blueprint import documents

API = {"filename": "Acme-API.pdf", "pages": 12, "text": "# Acme Orders API\nGET /orders lists orders.", "truncated": False}
BRD = {"filename": "BRD.docx", "pages": 9, "text": "# Members\nA member places an order.", "truncated": False}


def test_a_document_on_a_question_turn_is_kept_for_the_next(tmp_path):
    out = str(tmp_path / "app")
    readable, evidence = bg._keep_documents(out, [API], [])
    assert readable == [API] and len(evidence) == 1 and "Acme Orders API" in evidence[0]
    # The next turn attaches only the BRD; both go with it, the API manual first.
    _, evidence = bg._keep_documents(out, [BRD], [])
    assert [("Acme" in e, "Members" in e) for e in evidence] == [(True, False), (False, True)]
    # A third turn with nothing attached still carries both, once each.
    _, evidence = bg._keep_documents(out, [], [])
    assert len(evidence) == 2 and len(documents.texts(out)) == 2


def test_the_integrations_agent_reads_the_documents(tmp_path):
    out = str(tmp_path / "app")
    bg._keep_documents(out, [API], [])
    assert "integrations" in documents.READS_DOCUMENTS
    assert "Acme Orders API" in documents.addendum(out, "integrations")


def test_the_definition_describes_the_app_in_the_persons_words():
    from services.smith4 import definition
    src = inspect.getsource(definition.define_application)
    assert "brief_mod.brief_from(ctx.history, ctx.message)" in src and "or brief_of(ctx)" not in src


def test_a_late_document_is_compared_and_offered_not_applied(tmp_path, monkeypatch):
    refreshed = []
    monkeypatch.setattr(bg, "_refresh_api_reference", lambda out: refreshed.append(out))
    out = tmp_path / "app"
    out.mkdir()
    early = bg._document_note(str(out), [BRD])
    assert "ARRIVED AFTER" not in early
    late = bg._document_note(str(out), [API], late=True)
    assert "ARRIVED AFTER THE REQUIREMENTS WERE WRITTEN" in late and "offer" in late
    assert "change nothing until they say" in late
    assert refreshed == [str(out), str(out)]
    # With a document attached, a message is not taken as a bare definition edit.
    assert "not readable_docs and _definition_edit(req.message)" in inspect.getsource(bg.smith_chat)


def test_a_late_api_manual_refreshes_the_reference_for_a_called_system(tmp_path, monkeypatch):
    from services.blueprint import api_reference
    from services.blueprint.service import BlueprintService

    class _Svc:
        doc = {"integrations": [{"id": "i1", "name": "Acme", "provider": "acme", "serves": ""}]}
    monkeypatch.setattr(BlueprintService, "load", classmethod(lambda cls, **kw: _Svc()))
    monkeypatch.setattr(api_reference, "called_by_http", lambda i: True)
    wrote = []
    monkeypatch.setattr(api_reference, "write", lambda out, doc: wrote.append(out) or [])
    bg._refresh_api_reference(str(tmp_path))
    assert wrote == [str(tmp_path)]
    # And nothing is called for an app with no outside system.
    _Svc.doc = {"integrations": []}
    bg._refresh_api_reference(str(tmp_path))
    assert wrote == [str(tmp_path)]
