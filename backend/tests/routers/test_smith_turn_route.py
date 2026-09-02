"""POST /api/projects/{id}/smith/turn — the conversational layer over HTTP.

The point of this endpoint is not its response body. It is that running the
Blueprint DAG from a request makes the virtual office move: the office narrates
onto the project's event bus *while* the turn is in flight, and the browser is
already subscribed to that bus through ``/api/projects/{id}/events``. So the
assertions here are mostly about what the office received.

A fake model stands in for Anthropic — the route's job is orchestration, and a
test that needed an API key would not run.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from services.project_event_bus import subscribe

FLEET = Path(__file__).resolve().parents[2] / "fleet" / "blueprints"

PROJECT = "officeapp"

#: A request that actually reaches the DAG. The preview anchors matter: without
#: something concrete to point at, impact analysis comes back empty and
#: `apply_change` returns before any agent runs — a legitimate outcome, but not
#: the one these tests are about.
TURN = {
    "text": "make the candidate table compact",
    "page": "PAGE-009",
    "component": "CMP-033",
}


class FakeModel:
    """Answers every prompt with the same envelope: understood, no proposals.

    Enough to drive a whole turn — Smith interprets, `apply_change` finds the
    impacted sub-DAG, and every agent the DAG reaches returns a well-formed
    empty result. Which is the interesting path here: the office should show
    the run regardless of whether an artifact changed.
    """

    enforces_schema = True
    model = "fake"

    def __call__(self, *, system: str, user: str, schema: dict) -> str:
        if "you are smith" in system.lower():
            return json.dumps({
                "intent": "change",
                "summary": "make the candidate table compact",
                "reply": "Done — the table is compact now.",
                "anchors": ["CMP-033"],
                "proposals": [],
                "answers": [],
                # §17: below ASK_USER nothing is applied, so a test that wants
                # the DAG to run has to be confident about what it asked for.
                "confidence": 1.0,
            })
        return json.dumps({
            "task_id": "TASK-fake", "agent": "smith", "status": "completed",
            "proposals": [], "requirements_satisfied": [], "tests_generated": [],
            "assumptions": [], "change_requests": [], "confidence": 1.0,
        })


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A project on disk, at ``OUTPUT_ROOT/officeapp``, with a real Blueprint."""
    import services.project_paths as pp
    from services.blueprint.service import BlueprintService
    from services.smith.smith import bootstrap

    monkeypatch.setattr(pp, "OUTPUT_ROOT", tmp_path)
    root = tmp_path / PROJECT
    root.mkdir(parents=True)

    svc = BlueprintService(output_dir=str(root))
    svc.doc = json.loads((FLEET / "ats-live.json").read_text("utf-8"))
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)
    return root


#: ``/api/projects/{id}/events`` declares ``project_id: uuid.UUID``, so the
#: browser can only ever subscribe with a UUID. The turn endpoint accepts a
#: short_id too (the editor addresses projects that way), and publishes under
#: whatever it was given — see the id-mismatch test below for why that matters.
PROJECT_UUID = "3f1c9d54-0b0e-4a2c-9d1e-7c5b2a6f8e40"


@pytest.fixture()
def uuid_addressed(project, monkeypatch):
    """Let the UUID resolve to the same directory, without a database."""
    import routers.output_projects as mod

    async def resolve(project_id: str):
        return project

    monkeypatch.setattr(mod, "_resolve_root", resolve)
    return PROJECT_UUID


@pytest.fixture()
def fake_model(monkeypatch):
    import routers.output_projects as mod
    monkeypatch.setattr(mod, "_smith_model", lambda name: FakeModel())
    return FakeModel()


async def _client() -> AsyncClient:
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _drain(queue: asyncio.Queue, *, timeout: float = 0.5) -> list[dict]:
    """Everything already on a bus queue, without blocking on more."""
    out: list[dict] = []
    while True:
        try:
            out.append(await asyncio.wait_for(queue.get(), timeout=timeout))
        except asyncio.TimeoutError:
            return out


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_project_without_a_blueprint_is_refused_not_crashed(tmp_path, monkeypatch):
    import services.project_paths as pp
    monkeypatch.setattr(pp, "OUTPUT_ROOT", tmp_path)
    (tmp_path / PROJECT).mkdir()

    async with await _client() as client:
        r = await client.post(f"/api/projects/{PROJECT}/smith/turn",
                              json={"text": "make it compact"})
    assert r.status_code == 409
    assert "Blueprint" in r.json()["detail"]


@pytest.mark.asyncio
async def test_no_api_key_is_a_503_with_a_reason(project, monkeypatch):
    import routers.output_projects as mod
    monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr("config.ANTHROPIC_API_KEY", "")

    async with await _client() as client:
        r = await client.post(f"/api/projects/{PROJECT}/smith/turn",
                              json={"text": "make it compact"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Which conversation is this?
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_warmup_reports_whether_the_project_has_a_blueprint(project):
    """The chat panel routes on this, so it has to be a fact and not a guess.

    Reported by warmup rather than a probe of its own because the panel
    already fires warmup on mount — one call, one answer.
    """
    async with await _client() as client:
        r = await client.post(f"/api/projects/{PROJECT}/smith/warmup")
    assert r.status_code == 200
    assert r.json()["blueprint"] is True


@pytest.mark.asyncio
async def test_warmup_says_no_blueprint_for_a_project_that_has_none(tmp_path, monkeypatch):
    """A project still waiting to be built keeps the streaming front door."""
    import services.project_paths as pp
    monkeypatch.setattr(pp, "OUTPUT_ROOT", tmp_path)
    (tmp_path / PROJECT).mkdir()

    async with await _client() as client:
        r = await client.post(f"/api/projects/{PROJECT}/smith/warmup")
    assert r.status_code == 200
    assert r.json()["blueprint"] is False


# ---------------------------------------------------------------------------
# The office animates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_turn_narrates_the_run_to_the_projects_office(project, fake_model):
    """The whole reason the endpoint exists."""
    async with subscribe(PROJECT) as q:
        async with await _client() as client:
            r = await client.post(f"/api/projects/{PROJECT}/smith/turn", json=TURN)
        assert r.status_code == 200, r.text
        frames = await _drain(q)

    office = [f["office"] for f in frames if f.get("type") == "office"]
    assert office, "the turn ran but the office was never told"

    kinds = [e["type"] for e in office]
    # The roster comes first — the office greys out everyone not on this plan
    # before anybody starts moving.
    assert kinds[0] == "run_plan"
    assert {"agent_start", "agent_complete"} & set(kinds)


@pytest.mark.asyncio
async def test_every_narrated_agent_is_one_the_office_can_move(project, fake_model):
    """A frame naming an agent with no desk is a frame the office drops."""
    from services.office_events import ROOM_OF

    async with subscribe(PROJECT) as q:
        async with await _client() as client:
            await client.post(f"/api/projects/{PROJECT}/smith/turn", json=TURN)
        frames = await _drain(q)

    assert frames, "nothing was narrated, so this asserts nothing"
    for frame in frames:
        evt = frame.get("office") or {}
        for key in ("agent", "from", "to"):
            if key in evt:
                assert evt[key] in ROOM_OF, evt


@pytest.mark.asyncio
async def test_the_bus_is_keyed_by_the_id_the_browser_subscribed_with(project, fake_model):
    """``project_id`` is passed through verbatim rather than resolved to a
    short_id first. Resolve it and the frames land on a stream nobody is
    listening to — the office would sit still and nothing would look broken."""
    async with subscribe("some-other-project") as wrong:
        async with subscribe(PROJECT) as right:
            async with await _client() as client:
                await client.post(f"/api/projects/{PROJECT}/smith/turn", json=TURN)
            assert await _drain(right)
        assert await _drain(wrong, timeout=0.1) == []


@pytest.mark.asyncio
async def test_a_short_id_turn_animates_nothing_because_nobody_can_subscribe(
    project, fake_model,
):
    """A constraint worth pinning rather than discovering.

    ``/events`` is typed ``uuid.UUID``; the turn endpoint accepts a short_id as
    well and keys the bus on whatever it was handed. So a short_id turn
    publishes to a channel no browser can open — the run succeeds and the
    office never moves, with nothing in the console to explain it. The client
    must call the turn with the same id it opened the stream with.
    """
    async with await _client() as client:
        stream = await client.get(f"/api/projects/{PROJECT}/events",
                                  headers={"Accept": "text/event-stream"})
    assert stream.status_code == 422, (
        "if /events starts accepting a short_id, the turn endpoint's id no "
        "longer has to be a UUID and this constraint can go"
    )


@pytest.mark.asyncio
async def test_run_agents_false_still_reports_but_does_not_regenerate(project, fake_model):
    async with await _client() as client:
        r = await client.post(f"/api/projects/{PROJECT}/smith/turn",
                              json={**TURN, "run_agents": False})
    assert r.status_code == 200
    assert r.json()["run"] is None


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_office_frames_reach_the_browser_in_the_shape_it_parses(
    project, fake_model, uuid_addressed,
):
    """DAG -> bus -> /events -> the payload ChatPanel destructures.

    The bus test above proves the frames were published. This one proves they
    survive the SSE endpoint in the shape the client reads: event name
    ``office``, and a JSON body carrying the office event under ``office``.
    Get either wrong and the office sits still with nothing in the console to
    explain it — the frames arrive and are silently ignored.

    Driven through the endpoint's own body iterator rather than an HTTP client:
    httpx's ASGI transport does not stream, so a never-ending SSE response over
    it yields nothing at all.
    """
    from routers.project_events import project_events

    response = await project_events(uuid.UUID(PROJECT_UUID))
    frames = response.body_iterator

    ready = await frames.__anext__()
    assert ready["event"] == "ready"

    async with await _client() as client:
        post = asyncio.create_task(
            client.post(f"/api/projects/{PROJECT_UUID}/smith/turn", json=TURN)
        )
        first = await asyncio.wait_for(frames.__anext__(), timeout=10)
        r = await post
    assert r.status_code == 200, r.text

    assert first["event"] == "office", first
    payload = json.loads(first["data"])
    assert "office" in payload, payload
    assert payload["office"]["type"] == "run_plan"
    assert isinstance(payload["office"]["agents"], list)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_turns_on_one_project_do_not_overlap(project, fake_model):
    """Both would read the Blueprint, both would commit, and the second would
    version a document it never saw."""
    import routers.output_projects as mod

    live = 0
    peak = 0
    real_to_thread = asyncio.to_thread

    async def tracked(fn, *a, **kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            return await real_to_thread(fn, *a, **kw)
        finally:
            live -= 1

    monkeypatched = mod.asyncio
    monkeypatched.to_thread = tracked  # type: ignore[assignment]
    try:
        async with await _client() as client:
            # `run_agents: False` on purpose. What is under test is the lock
            # around the Blueprint read-commit, which every turn takes whether
            # or not it goes on to regenerate — and regenerating three times
            # costs a minute to assert something the commit already proves.
            results = await asyncio.gather(*[
                client.post(f"/api/projects/{PROJECT}/smith/turn",
                            json={**TURN, "run_agents": False})
                for _ in range(3)
            ])
    finally:
        monkeypatched.to_thread = real_to_thread  # type: ignore[assignment]

    assert [r.status_code for r in results] == [200, 200, 200]
    assert peak == 1, f"{peak} turns ran against one Blueprint at once"
