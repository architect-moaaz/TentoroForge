"""A first build the platform starts itself (the Drafts Room's hand-off):
the builder's Smith is told in the transcript, the run registry shows it
active with its phase, the turn ledger marks it for the other worker, the
checks follow a hand-over, and a failure is said in the transcript.
"""
from __future__ import annotations

import asyncio
import glob
from types import SimpleNamespace

from routers import blueprint_generate as router
from services import run_registry

OPENING = "Build Threadline from the requirements document agreed in the Drafts Room.\n\nA wardrobe app."


def _project(tmp_path):
    return SimpleNamespace(id="p-handoff-" + tmp_path.name, name="Threadline", output_dir=str(tmp_path))


def test_the_build_runs_without_a_browser_and_its_checks_follow(tmp_path, monkeypatch):
    remembered: list = []
    monkeypatch.setattr(router, "_remember",
                        lambda loop, pid, role, text, meta=None, lock=None: remembered.append((role, text)))
    checks_started: list = []
    monkeypatch.setattr(router, "_start_checks",
                        lambda loop, pid, out, app, **kw: checks_started.append((pid, out, app)))
    seen: dict = {}

    def fake_dag(output_dir, app_root, description, *, approved, emit, app_name, documents, modules):
        seen.update(output_dir=output_dir, app_root=app_root, description=description, approved=approved,
                    app_name=app_name, documents=documents, modules=modules)
        emit("message", {"text": "Your application is built."})
        return {"status": "complete",
                "checks": {"output_dir": output_dir, "app_root": app_root, "pending": True}}
    monkeypatch.setattr(router, "_run_dag", fake_dag)
    project = _project(tmp_path)

    async def go():
        loop = asyncio.get_running_loop()
        fut = router.start_build_in_background(
            loop, project, message=OPENING, description="A wardrobe app.", documents=["# Threadline"],
            app_name="Threadline", output_dir=tmp_path, app_root=str(tmp_path / "app"))
        snap = run_registry.snapshot(project.id)
        assert snap["active"] and snap["phase"] == "build"
        assert run_registry.ledger_snapshot(tmp_path)["active"], "the other worker sees it running"
        await fut
        await asyncio.sleep(0.05)
    asyncio.run(go())

    assert seen == dict(output_dir=str(tmp_path), app_root=str(tmp_path / "app"), description="A wardrobe app.",
                        approved=True, app_name="Threadline", documents=["# Threadline"], modules=None)
    assert remembered[0] == ("user", OPENING), "the transcript opens with what Smith was told"
    assert remembered[1] == ("assistant", "Your application is built.")
    assert checks_started == [(project.id, str(tmp_path), str(tmp_path / "app"))]
    assert not run_registry.snapshot(project.id)["active"]
    assert glob.glob(str(tmp_path / ".forge" / "runs" / "*-smith-turn.jsonl"))
    assert not (run_registry.ledger_snapshot(tmp_path) or {}).get("active"), "the turn ledger is ended"


def test_a_build_that_fails_says_so_in_the_transcript(tmp_path, monkeypatch):
    remembered: list = []
    monkeypatch.setattr(router, "_remember",
                        lambda loop, pid, role, text, meta=None, lock=None: remembered.append((role, text, meta)))
    monkeypatch.setattr(router, "_start_checks", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no checks")))

    def fake_dag(*a, **k):
        raise RuntimeError("the executor is gone")
    monkeypatch.setattr(router, "_run_dag", fake_dag)
    project = _project(tmp_path)

    async def go():
        loop = asyncio.get_running_loop()
        fut = router.start_build_in_background(
            loop, project, message=OPENING, description="A wardrobe app.", documents=[],
            app_name="Threadline", output_dir=tmp_path, app_root=str(tmp_path / "app"))
        try:
            await fut
        except RuntimeError:
            pass
        await asyncio.sleep(0.05)
    asyncio.run(go())

    assert remembered[0][:2] == ("user", OPENING)
    role, text, meta = remembered[1]
    assert role == "assistant" and "Something went wrong" in text and "RuntimeError" in text
    assert meta == {"status": "error"}
    assert not run_registry.snapshot(project.id)["active"]
    assert not (run_registry.ledger_snapshot(tmp_path) or {}).get("active")
