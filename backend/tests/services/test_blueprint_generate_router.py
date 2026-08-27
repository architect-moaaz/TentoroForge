"""The seam between the product surface and the Blueprint engine.

Everything built against the PRD was reachable only from a CLI, so the platform
and the engine were two different systems: `/generate` drove the 582-service
chain this rebuild exists to replace, and nothing in the API layer imported
`services.blueprint` at all.
"""
from __future__ import annotations


def test_the_new_route_is_registered_beside_the_legacy_one():
    """Beside, not instead. The old path keeps working while this is proven,
    and a caller can tell from the URL which engine it asked for."""
    import main

    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert "/api/projects/{project_id}/generate/blueprint" in paths
    assert "/api/projects/{project_id}/generate" in paths, (
        "the legacy endpoint must not be removed by wiring the new one")


def test_the_router_drives_the_blueprint_engine_not_the_chain():
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate)
    assert "services.blueprint.orchestrator" in src
    assert "generation_chain" not in src and "agent_from_plan" not in src


def test_it_projects_beside_the_blueprint_so_projections_are_not_blocked():
    """A projection with no app root blocks and takes its dependents with it —
    that is how an incremental change silently ran a handful of eighteen nodes."""
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert 'output_dir / "app"' in src
    assert "app_root=app_root" in src


def test_the_report_names_what_did_not_run():
    """Counting skips is not enough: a plan that quietly drops nodes reads
    exactly like one that ran them and found nothing to do."""
    from dataclasses import dataclass, field

    from routers.blueprint_generate import _report_payload

    @dataclass
    class R:
        completed: list = field(default_factory=lambda: ["requirements"])
        skipped: list = field(default_factory=lambda: ["apis"])
        blocked: list = field(default_factory=list)
        failed: list = field(default_factory=list)
        skipped_because: dict = field(default_factory=lambda: {"apis": "database"})

    payload = _report_payload(R())
    assert payload["skipped"] == [{"node": "apis", "unmet": "database"}]


def test_define_only_stops_before_the_expensive_half():
    """§114 step 4 proposes before it regenerates; a first build deserves the
    same courtesy, because the definition is cheap and the DAG is not."""
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert "define_only" in src and '"application_model"' in src


def test_progress_events_cross_the_thread_boundary_safely():
    """The run happens in an executor thread; the queue belongs to the loop.

    `Queue.put_nowait` called straight from the worker appends without waking
    the loop, so the consumer stays blocked and every event lands at once when
    the future resolves. The first live request showed exactly that: ninety
    seconds of keep-alive pings, then the whole run's progress in one burst.
    §111 asks for observable status, and a burst at the end is not it.
    """
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    # Every hand-off into the queue goes through the loop, including the
    # sentinel that ends the stream.
    assert "call_soon_threadsafe(\n            queue.put_nowait," in src \
        or "call_soon_threadsafe(queue.put_nowait" in src
    assert "call_soon_threadsafe(queue.put_nowait, None)" in src
    # and never straight from the worker thread
    assert "        queue.put_nowait({" not in src


async def test_an_event_emitted_from_a_thread_reaches_the_consumer():
    """The behaviour, not just the call shape."""
    import asyncio

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def emit(item):
        loop.call_soon_threadsafe(q.put_nowait, item)

    def work():
        emit("node:start")
        emit("node:done")
        emit(None)

    asyncio.get_running_loop().run_in_executor(None, work)
    got = []
    while True:
        item = await asyncio.wait_for(q.get(), timeout=2)
        if item is None:
            break
        got.append(item)
    assert got == ["node:start", "node:done"]


def _seed(tmp_path):
    """A Blueprint with a user decision and a stable id in it."""
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="p",
                                  name="Mark 1", domain="Workshop",
                                  description="original intent")
    svc.upsert("requirements", {"description": "A member borrows a book."},
               natural_key="borrow")
    svc.doc["decisions"] = [{
        "id": "DEC-001", "decision": "Sign-off above 2,000,000",
        "source": "user", "reason": "the user said so",
    }]
    svc.save()
    return svc


def test_a_second_generate_resumes_rather_than_overwriting(tmp_path):
    """Creating unconditionally made clicking generate twice destructive.

    A Blueprint carries the decisions the user made (§20) and the stable ids
    every projected file is keyed to (§12). Replacing one silently is not a
    regeneration, it is amnesia.
    """
    from services.blueprint.service import BlueprintService

    _seed(tmp_path)
    existing = tmp_path / ".forge" / "blueprint" / "current.json"
    assert existing.is_file()

    # what the router does on a resume
    svc = BlueprintService.load(output_dir=str(tmp_path))
    assert [d["id"] for d in svc.doc["decisions"]] == ["DEC-001"]
    assert len(svc.doc["requirements"]) == 1
    assert svc.doc["requirements"][0]["id"] == "REQ-001"


def test_starting_over_is_possible_but_has_to_be_asked_for(tmp_path):
    from services.blueprint.service import BlueprintService

    _seed(tmp_path)
    fresh = BlueprintService.create(output_dir=str(tmp_path), app_id="p",
                                    name="Mark 1", domain="Workshop",
                                    description="new intent")
    # A newly created document has no artifacts at all — the sections are
    # absent rather than empty, which is what `create` means.
    assert not fresh.doc.get("requirements")
    assert not fresh.doc.get("decisions")


def test_the_router_resumes_by_default_and_reports_which_it_did():
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert "BlueprintService.load" in src, "must be able to resume at all"
    assert "not req.fresh" in src, "resume must be the default, fresh opt-in"
    assert '"resumed": resumed' in src, "the client has to know which happened"

    # `fresh` defaults to off, so the destructive path is never the default
    assert blueprint_generate.BlueprintGenerateRequest(
        description="x").fresh is False
