"""A phone-only app has no website, so the free `page_layouts` node makes no web trees for it.

It used to make a tree for every page and the `frontend` projection built each into a real web page: Cart Buddy's live address
showed a Shopping List table for an app that is only a phone app."""
from __future__ import annotations

import types

from services.blueprint import orchestrator as orch
from services.blueprint import template_page

PAGES = [
    {"id": "PAGE-001", "name": "Shopping List", "route": "/", "pattern": "list"},
    {"id": "PAGE-002", "name": "Bought", "route": "/bought", "pattern": "list"},
    {"id": "PAGE-004", "name": "Sign in", "route": "/login", "pattern": "auth"},
]


def compose(monkeypatch, surface):
    doc = {"pages": [dict(p) for p in PAGES], "pageLayouts": []}
    if surface:
        doc["mobile"] = {"surface": surface}
    svc = types.SimpleNamespace(doc=doc, output_dir="/nowhere")
    written = []
    monkeypatch.setattr(orch, "apply_agent_result",
                        lambda s, result, commit=True: written.append(result.proposals[0].natural_key))
    monkeypatch.setattr(template_page, "template_layout", lambda d, page: {"page": page["id"], "root": {}, "dataSources": []})
    orch._compose_page_layouts(svc)
    return written


def test_a_phone_only_app_gets_no_trees(monkeypatch):
    assert compose(monkeypatch, "native_only") == []


def test_every_other_choice_still_gets_a_tree_for_each_page_but_the_sign_in_page(monkeypatch):
    for surface in (None, "web", "web_native", "web_pwa", "pwa_only"):
        assert compose(monkeypatch, surface) == ["PAGE-001", "PAGE-002"], surface
