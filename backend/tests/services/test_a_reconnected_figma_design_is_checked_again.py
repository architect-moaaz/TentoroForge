"""Connecting a Figma design again drops the verdict about the one connected before.

Review of 58103bc3: the stored coverage verdict stayed after a re-connect, so a design swapped for another
one went through `figma_gate.stop` as already judged."""
from __future__ import annotations

import json

import pytest

from services.figma import store
from services.smith import figma_gate


@pytest.fixture()
def out(tmp_path):
    figma_gate._write(tmp_path, {"decision": "ok", "sufficient": True, "url": "https://figma.com/x", "report": "ok"})
    return tmp_path


def test_forgetting_removes_the_verdict(out):
    assert figma_gate._read(out) is not None
    store.forget_coverage(out)
    assert figma_gate._read(out) is None


def test_forgetting_with_no_verdict_is_fine(tmp_path):
    store.forget_coverage(tmp_path)


def test_connect_forgets_the_old_verdict(out, monkeypatch):
    class Svc:
        output_dir = str(out)
        doc: dict = {}

        def save(self):
            pass

    monkeypatch.setattr(store, "save", lambda ref, output_dir: None)
    monkeypatch.setattr(store, "source_record", lambda ref, name="", treat_as="evidence": {"id": "FIGMA-001"})
    monkeypatch.setattr(store, "_chrome_evidence", lambda ref: None)
    monkeypatch.setattr(store, "_frame_headings", lambda ref: {})
    store.connect(Svc(), object())
    assert figma_gate._read(out) is None, "the design was read again, so nobody has checked it yet"
