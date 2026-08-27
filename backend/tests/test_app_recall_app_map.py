"""AM-4 — assemble_recall + RecallContext.to_prompt_block prepend the
app-map skeleton so Smith opens every turn already knowing the app."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from services import app_map as am
from services.app_recall import assemble_recall


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture(autouse=True)
def _fresh_cache():
    am.clear_app_map_cache()
    yield
    am.clear_app_map_cache()


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "contracts").mkdir()
    for name in ("resource-registry.json", "action-contract.json",
                 "generation-dossier.json"):
        shutil.copy(_FIXTURE / "contracts" / name, tmp_path / "contracts" / name)
    shutil.copy(_FIXTURE / "registry.json", tmp_path / "registry.json")
    shutil.copytree(_FIXTURE / "src" / "schemas", tmp_path / "src" / "schemas")
    return tmp_path


def test_prompt_block_starts_with_app_map(app_root):
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    # The map header must be the very first thing — before APP INTENT — so
    # Smith reads the shape before anything else.
    assert block.startswith("# APP MAP")


def test_prompt_block_contains_app_intent_after_map(app_root):
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    # The recall's own APP INTENT header still appears below the map.
    map_idx = block.find("# APP MAP")
    intent_idx = block.find("APP INTENT:")
    assert map_idx < intent_idx, "app-map must precede recall body"


def test_prompt_block_names_every_entity(app_root):
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    for name in ("Candidate", "Application", "Interview",
                 "RecruitmentDrive", "User", "CommunicationLog"):
        assert name in block, f"{name} missing from prompt block"


def test_prompt_block_lists_key_routes(app_root):
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    assert "/candidates/new" in block
    assert "/candidates/:id/edit" in block


def test_prompt_block_names_workflows(app_root):
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    assert "create-candidate" in block
    assert "InterviewSchedulingWorkflow" in block


def test_backward_compat_recall_without_output_dir_still_renders():
    """Constructing a RecallContext directly (no output_dir) must not
    crash when to_prompt_block() runs. Older callers do this."""
    from services.app_recall import RecallContext
    ctx = RecallContext(prompt="test prompt")
    block = ctx.to_prompt_block()
    # No map (no output_dir means no prefix), but the recall body must
    # still render.
    assert "# APP MAP" not in block
    assert "APP INTENT" in block


def test_map_prefix_survives_broken_contracts(app_root, monkeypatch):
    """If the app-map builder raises, prompt block still renders — the
    map is a nice-to-have, not a hard dependency."""
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated corruption")
    monkeypatch.setattr("services.app_map.get_app_map", _boom)
    recall = assemble_recall(str(app_root))
    block = recall.to_prompt_block()
    # Map missing, recall body still there.
    assert "APP INTENT" in block
