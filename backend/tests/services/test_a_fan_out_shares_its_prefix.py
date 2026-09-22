"""A fan-out's calls share everything they can, and the cache is told so.

HippieKit's measured build (2026-09-21) cost $16.50, and 39% of it was input
sent at full price: 3.2M tokens. Only the system prompt was cached. Each
page_details call re-sent the same page set and Blueprint slice AFTER its own
pages, so no two calls shared a prefix past the system prompt: 882k input
over 27 calls, 63k read back from the cache, and 126k written to it for
nothing. The shared part now comes first, and the client caches up to it.
"""
from __future__ import annotations

import pytest

from services.blueprint.executors import CACHE_BREAK, CACHE_MIN_TOKENS, _content, _user_blocks
from services.blueprint.executors import build_prompt
from services.blueprint.service import BlueprintService


def test_a_big_shared_head_is_cached_and_the_tail_is_not():
    head = "x" * (CACHE_MIN_TOKENS * 4 + 10)
    blocks = _user_blocks(head + CACHE_BREAK + "this subject")
    assert blocks[0] == {"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in blocks[1] and blocks[1]["text"].endswith("this subject")


def test_a_small_head_or_no_break_stays_a_plain_string():
    assert _user_blocks("short" + CACHE_BREAK + "tail") == "short" + CACHE_BREAK + "tail"
    assert _user_blocks("no break at all") == "no break at all"


def test_images_still_lead_and_keep_one_breakpoint_each():
    import base64
    import tempfile
    from pathlib import Path

    png = Path(tempfile.mkdtemp()) / "a.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="))
    head = "x" * (CACHE_MIN_TOKENS * 4 + 10)
    content = _content([png], head + CACHE_BREAK + "tail")
    assert [b["type"] for b in content] == ["image", "text", "text"]
    # system + image + shared head: three of the four breakpoints allowed.
    assert sum("cache_control" in b for b in content) == 2


@pytest.fixture()
def doc(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="ops")
    svc.doc["requirements"] = [{"id": f"REQ-{i:03d}", "title": f"r{i}", "statement": "s" * 40}
                               for i in range(1, 6)]
    svc.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "Member", "table": "members", "requirements": ["REQ-001"],
         "fields": [{"name": "id", "type": "uuid"}]},
        {"id": "ENTITY-002", "name": "Tool", "table": "tools", "requirements": ["REQ-002"],
         "fields": [{"name": "id", "type": "uuid"}]}],
        "relationships": [{"from": "ENTITY-002", "to": "ENTITY-001", "kind": "many_to_one"}]}
    svc.doc["pages"] = [
        {"id": "PAGE-001", "route": "/members/[id]", "name": "Member", "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-002", "route": "/tools/[id]", "name": "Tool", "data": {"primaryEntity": "ENTITY-002"}}]
    svc.doc["workflows"] = [
        {"id": "FLOW-001", "name": "Join", "requirements": ["REQ-001"]},
        {"id": "FLOW-002", "name": "Lend", "requirements": ["REQ-002"], "steps": [{"id": "s"}]}]
    return svc.doc


@pytest.mark.parametrize("node, agent, subjects", [
    ("entity_fields", "data_model", ["ENTITY-001", "ENTITY-002"]),
    ("page_details", "page_design", ["ENTITY-001", "ENTITY-002"]),
    ("workflow_steps", "workflow", ["FLOW-001", "FLOW-002"]),
])
def test_every_subject_of_a_fan_out_shares_one_head(doc, node, agent, subjects):
    parts = [build_prompt(doc, node, subject=s, agent=agent)[1].partition(CACHE_BREAK) for s in subjects]
    assert all(sep for _, sep, _ in parts)
    assert len({head for head, _, _ in parts}) == 1, "a subject's own data leaked into the shared head"
    # Each subject is asked for in its own tail. (Its id may also appear in
    # the head — the entity list names every entity — which is the point.)
    for s, (_, _, tail) in zip(subjects, parts):
        assert s in tail.split("\n", 1)[0]


def test_the_subject_still_gets_the_requirements_it_answers(doc):
    _, user = build_prompt(doc, "workflow_steps", subject="FLOW-001", agent="workflow")
    import json
    import re

    _, _, tail = user.partition(CACHE_BREAK)
    own = json.loads(re.search(r"```json\n(.*)\n```", tail, re.S).group(1))
    assert [r["id"] for r in own["requirements"]] == ["REQ-001"]
    assert [w["id"] for w in own["workflows"]] == ["FLOW-001"]
