"""Find problems and the Test console spend the PLATFORM's model key, so they are metered like all other paid work.

What is pinned: the same door as the build and Smith (HTTP 402 in the administrator's words, before the first call), a hard
cap on the model calls of one run, the model name and answer length held to what the server allows (the drawing is not
trusted for either), and every call's real usage written to the ledger under the application, the person and the
organisation that spent it. Driven with a fake model, so nothing is spent."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every model before test_db.create_all)
from services import agent_spend as sp
from tests.routers.test_agent_builder_runtime import GRAPH as CONSOLE_GRAPH
from tests.services.test_agent_runtime_install import graph, node


class Model:
    """Stands in for anthropic.AsyncAnthropic: remembers every request, answers with fixed usage."""

    def __init__(self, input_tokens=100, output_tokens=40):
        self.requests: list[dict] = []
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                                     cache_read_input_tokens=0, cache_creation_input_tokens=0)
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **req):
        self.requests.append(req)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn", usage=self.usage)


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return lambda: [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# -- the model and the answer length are the server's to decide ----------------

def test_a_model_the_platform_allows_is_kept_and_any_other_is_replaced_with_a_note(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("FORGE_BLAST_MODEL", raising=False)
    monkeypatch.delenv("FORGE_AGENT_TEST_MODELS", raising=False)
    assert sp.clamp_model("claude-haiku-4-5") == ("claude-haiku-4-5", "")
    assert sp.clamp_model("claude-haiku-4-5-20251001") == ("claude-haiku-4-5-20251001", ""), "a dated id of an allowed model is allowed"
    assert sp.clamp_model(None) == ("claude-sonnet-4-6", "") and sp.clamp_model("  ") == ("claude-sonnet-4-6", "")
    used, note = sp.clamp_model("claude-opus-4-8")
    assert used == "claude-sonnet-4-6" and "claude-opus-4-8" in note and "claude-sonnet-4-6" in note
    assert sp.clamp_model("not-a-model-at-all")[0] == "claude-sonnet-4-6"


def test_more_models_can_be_allowed_with_the_environment_and_the_platforms_own_is_always_allowed(monkeypatch):
    monkeypatch.setenv("FORGE_AGENT_TEST_MODELS", "claude-opus-4-8, claude-haiku-5")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    assert sp.clamp_model("claude-opus-4-8") == ("claude-opus-4-8", "")
    assert sp.clamp_model("claude-sonnet-5") == ("claude-sonnet-5", "")
    assert sp.clamp_model("claude-opus-5")[0] == "claude-sonnet-5", "anything else gets the platform's model"


def test_the_answer_length_is_cut_to_the_server_maximum_and_nonsense_gets_the_maximum():
    assert sp.clamp_max_tokens(2048) == 2048
    assert sp.clamp_max_tokens(10**9) == sp.MAX_OUTPUT_TOKENS
    assert sp.clamp_max_tokens(-5) == 1
    assert sp.clamp_max_tokens("lots") == sp.MAX_OUTPUT_TOKENS and sp.clamp_max_tokens(None) == sp.MAX_OUTPUT_TOKENS


# -- the meter: a hard cap, counted before the call, plain words ---------------

@pytest.mark.asyncio
async def test_the_call_over_the_cap_is_never_made_and_says_why_in_plain_words():
    model = Model()
    client = sp.Meter(agent="agent_blast", max_calls=2).wrap(model)
    await client.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[])
    await client.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[])
    with pytest.raises(sp.CallLimitReached) as e:
        await client.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[])
    assert len(model.requests) == 2, "the third call never reached the platform's key"
    assert "limit of 2 model calls" in str(e.value) and isinstance(e.value, RuntimeError)
    assert client.meter.calls == 2 and client.meter.stopped == str(e.value)


@pytest.mark.asyncio
async def test_every_call_is_clamped_whatever_the_caller_asked_for(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("FORGE_BLAST_MODEL", raising=False)
    model = Model()
    await sp.Meter(agent="agent_blast").wrap(model).messages.create(model="claude-opus-4-8", max_tokens=10**7, system="s", messages=[])
    sent = model.requests[0]
    assert sent["model"] == "claude-sonnet-4-6" and sent["max_tokens"] == sp.MAX_OUTPUT_TOKENS and sent["system"] == "s"


@pytest.mark.asyncio
async def test_real_usage_is_recorded_under_the_application_the_person_and_the_organisation(ledger):
    meter = sp.Meter(agent="agent_blast", project="abc123", user="pat@example.com", org="org-9")
    await meter.wrap(Model(input_tokens=1234, output_tokens=56)).messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[])
    (row,) = ledger()
    assert (row["project"], row["agent"], row["user"], row["org"]) == ("abc123", "agent_blast", "pat@example.com", "org-9")
    assert (row["input_tokens"], row["output_tokens"], row["model"]) == (1234, 56, "claude-haiku-4-5")
    assert row["kind"] == "agent_test" and row["phase"] == "change" and row["est_cost_usd"] > 0, "priced, so limits and balances see it"
    assert (meter.input_tokens, meter.output_tokens) == (1234, 56)


@pytest.mark.asyncio
async def test_a_meter_without_an_application_counts_and_caps_but_writes_nothing(ledger):
    meter = sp.Meter(agent="agent_blast", max_calls=5)
    await meter.wrap(Model()).messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[])
    assert meter.calls == 1 and ledger() == []


@pytest.mark.asyncio
async def test_a_lazy_client_is_made_on_its_first_call_so_a_missing_key_is_said_there():
    made = []

    def make():
        made.append(1)
        return Model()

    client = sp.Meter(agent="agent_blast").client(make)
    assert made == []
    await client.messages.create(model="claude-haiku-4-5", max_tokens=1, messages=[])
    await client.messages.create(model="claude-haiku-4-5", max_tokens=1, messages=[])
    assert made == [1]

    def no_key():
        raise RuntimeError("Finding problems needs a model key.")

    with pytest.raises(RuntimeError, match="needs a model key"):
        await sp.Meter(agent="agent_blast").client(no_key).messages.create(model="x", max_tokens=1, messages=[])


def test_wrapping_a_metered_client_again_keeps_the_first_meter():
    once = sp.Meter(agent="a", max_calls=1).wrap(Model())
    assert sp.Meter(agent="b").wrap(once) is once


# -- the door: the same 402 as the build and every Smith turn ------------------

@pytest.mark.asyncio
async def test_the_gate_is_the_platforms_own_door_and_prices_the_calls(monkeypatch):
    seen = {}

    async def refusal(db, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr("services.credits.refusal", refusal)
    project = SimpleNamespace(org_id="org-1", short_id="abc123")
    await sp.gate(None, project, SimpleNamespace(email="pat@example.com"), calls=100)
    assert seen["org_id"] == "org-1" and seen["project_short_id"] == "abc123" and seen["user_email"] == "pat@example.com"
    assert seen["estimate"] == pytest.approx(100 * sp.ESTIMATE_PER_CALL_USD)


@pytest.mark.asyncio
async def test_an_organisation_that_cannot_pay_is_refused_with_a_402_before_anything_runs(monkeypatch):
    async def refusal(db, **kw):
        return ["the organisation Acme holds $0.00 and this is expected to cost about $0.02, add credit before it starts"]

    monkeypatch.setattr("services.credits.refusal", refusal)
    with pytest.raises(HTTPException) as e:
        await sp.gate(None, SimpleNamespace(org_id="o", short_id="p"), SimpleNamespace(email="x@y.z"), calls=1)
    assert e.value.status_code == 402 and e.value.detail.startswith("Not started:") and "Acme" in e.value.detail


@pytest.mark.asyncio
async def test_the_real_balance_decides(test_db, ledger):
    """No fake: an organisation holding five cents may test one message but not run a blast."""
    from database import async_session
    from services import credits

    org = uuid.uuid4()
    async with async_session() as db:
        await credits.add_entry(db, org, 0.05, "opening", "test credit", None)
        await db.commit()
    project = SimpleNamespace(org_id=org, short_id="abc123")
    async with async_session() as db:
        await sp.gate(db, project, SimpleNamespace(email="pat@example.com"), calls=1)
        with pytest.raises(HTTPException) as e:
            await sp.gate(db, project, SimpleNamespace(email="pat@example.com"), calls=250)
    assert e.value.status_code == 402 and "$0.05" in e.value.detail


# -- the routers: every endpoint that spends the key goes through the door -----

@pytest.fixture()
def project(monkeypatch, tmp_path):
    (tmp_path / "agent-definitions").mkdir()
    (tmp_path / "agent-definitions" / "support.json").write_text(json.dumps(CONSOLE_GRAPH), encoding="utf-8")
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(tmp_path), short_id="abc123", org_id="org-1")

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    return proj


USER = SimpleNamespace(id="u", email="pat@example.com")


def drawn():
    from schemas.agent_builder import AgentDefinitionSave

    return AgentDefinitionSave(**graph(node("sp", "system_prompt", "P", {"prompt": "You help."})))


def _endpoints(project):
    """Every endpoint that makes model calls on the platform's key: (name, how to call it, the service function it must not reach)."""
    from routers import agent_builder as r
    from schemas import agent_builder as s

    pid = project.id
    return [
        ("invent", lambda: r.blast_invent(pid, "support", s.AgentBlastInvent(graph=drawn()), USER, None), "services.agent_blast.invent_bombs"),
        ("tool-tests", lambda: r.blast_tool_tests(pid, "support", s.AgentBlastTool(graph=drawn(), tool="x"), USER, None), "services.agent_blast.invent_tool_tests"),
        ("write-tests", lambda: r.write_agent_tests(pid, "support", s.AgentBlastWrite(graph=drawn()), USER, None), "services.agent_blast.write_tests"),
        ("run", lambda: r.blast_run(pid, "support", s.AgentBlastRun(graph=drawn(), tests=[{"name": "n", "message": "m"}]), USER, None), "services.agent_blast.blast"),
        ("fixes", lambda: r.blast_fixes(pid, "support", s.AgentBlastFixes(graph=drawn(), results=[]), USER, None), "services.agent_blast.propose_fixes"),
        ("recordings", lambda: r.send_recorded_chats(pid, "support", s.AgentRecordingSend(chats=[{"x": 1}], fix=True, graph=drawn()), USER, None), "services.agent_recording.send"),
        ("console", lambda: r.test_agent(pid, "support", s.AgentTestRequest(message="hi"), USER, None), "services.agent_test_run.run_agent_test"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["invent", "tool-tests", "write-tests", "run", "fixes", "recordings", "console"])
async def test_every_endpoint_that_spends_the_key_is_refused_with_a_402_when_the_organisation_cannot_pay(project, monkeypatch, which):
    async def refusal(db, **kw):
        return ["the organisation Acme holds $0.00 and this is expected to cost about $0.02, add credit before it starts"]

    def must_not_run(*a, **kw):
        raise AssertionError("the model work started although the organisation cannot pay")

    monkeypatch.setattr("services.credits.refusal", refusal)
    _, call, target = next(e for e in _endpoints(project) if e[0] == which)
    monkeypatch.setattr(target, must_not_run)
    with pytest.raises(HTTPException) as e:
        await call()
    assert e.value.status_code == 402 and "Acme" in e.value.detail


@pytest.mark.asyncio
async def test_a_blast_is_priced_by_its_size_and_run_on_a_meter_that_names_who_pays_and_caps_the_calls(project, monkeypatch):
    from routers.agent_builder import blast_run
    from schemas.agent_builder import AgentBlastRun
    from services.agent_blast import estimate_blast_calls

    priced, seen = {}, {}

    async def refusal(db, **kw):
        priced.update(kw)
        return []

    async def fake(graph_, tests, *, repeats=1, meter=None, **kw):
        seen.update(meter=meter)
        yield {"type": "done", "summary": {}}

    monkeypatch.setattr("services.credits.refusal", refusal)
    monkeypatch.setattr("services.agent_blast.blast", fake)
    tests = [{"name": f"t{i}", "message": f"m{i}"} for i in range(10)]
    resp = await blast_run(project.id, "support", AgentBlastRun(graph=drawn(), tests=tests, repeats=3), USER, None)
    b"".join([c async for c in resp.body_iterator])
    meter = seen["meter"]
    assert (meter.project, meter.user, meter.org, meter.agent) == ("abc123", "pat@example.com", "org-1", "agent_blast")
    assert meter.max_calls == sp.MAX_BLAST_CALLS
    assert priced["estimate"] == pytest.approx(estimate_blast_calls(tests, 3) * sp.ESTIMATE_PER_CALL_USD)
    assert priced["estimate"] > 10 * sp.ESTIMATE_PER_CALL_USD, "a big blast is priced as a big blast, not as one call"


def test_the_blast_estimate_grows_with_the_blast_and_never_goes_past_the_cap():
    from services.agent_blast import estimate_blast_calls

    def many(n):
        return [{"name": f"n{i}", "message": f"m{i}"} for i in range(n)]

    assert estimate_blast_calls(many(1), 1) < estimate_blast_calls(many(20), 3)
    assert estimate_blast_calls(many(60), 3) <= sp.MAX_BLAST_CALLS
    assert estimate_blast_calls("not a list", "many") >= 1


@pytest.mark.asyncio
async def test_the_small_actions_run_on_a_meter_with_the_small_cap_and_keeping_recorded_chats_costs_nothing(project, monkeypatch):
    from routers.agent_builder import blast_invent, send_recorded_chats
    from schemas.agent_builder import AgentBlastInvent, AgentRecordingSend

    async def refusal(db, **kw):
        return []

    seen = {}

    async def fake_invent(graph_, bombs, per_bomb, *, client=None, **kw):
        seen["client"] = client
        return []

    async def fake_send(root, agent_id, chats, **kw):
        seen["send"] = kw
        return {"sent": 0}

    monkeypatch.setattr("services.credits.refusal", refusal)
    monkeypatch.setattr("services.agent_blast.invent_bombs", fake_invent)
    monkeypatch.setattr("services.agent_recording.send", fake_send)
    await blast_invent(project.id, "support", AgentBlastInvent(graph=drawn()), USER, None)
    assert seen["client"].meter.max_calls == sp.MAX_HELPER_CALLS and seen["client"].meter.project == "abc123"

    await send_recorded_chats(project.id, "support", AgentRecordingSend(chats=[{"x": 1}]), USER, None)
    assert seen["send"]["client"] is None, "no fixer, no model call, no meter"
    await send_recorded_chats(project.id, "support", AgentRecordingSend(chats=[{"x": 1}], fix=True, graph=drawn()), USER, None)
    assert seen["send"]["client"].meter.org == "org-1"


# -- the Test console ----------------------------------------------------------

@pytest.mark.asyncio
async def test_the_console_holds_the_drawings_model_and_length_to_the_servers_and_records_the_call(ledger, monkeypatch):
    import copy

    from services.agent_test_run import run_agent_test

    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    g = copy.deepcopy(CONSOLE_GRAPH)
    g["nodes"][0]["data"]["config"].update(model="claude-opus-4-8", max_tokens=900000)
    model = Model(input_tokens=300, output_tokens=20)
    meter = sp.Meter(agent="agent_test", project="abc123", user="pat@example.com", org="org-1", max_calls=3)
    out = await run_agent_test(g, "hello", [], client=model, meter=meter)
    sent = model.requests[0]
    assert sent["model"] == "claude-sonnet-4-6" and sent["max_tokens"] == sp.MAX_OUTPUT_TOKENS
    assert any("claude-opus-4-8" in w for w in out["warnings"]), "the builder is told their model was not the one used"
    assert out["model"] == "claude-sonnet-4-6"
    (row,) = ledger()
    assert (row["agent"], row["project"], row["user"], row["org"], row["input_tokens"]) == ("agent_test", "abc123", "pat@example.com", "org-1", 300)


@pytest.mark.asyncio
async def test_a_console_run_that_is_over_its_cap_says_so_instead_of_calling():
    from services.agent_test_run import run_agent_test

    model = Model()
    meter = sp.Meter(agent="agent_test", max_calls=1)
    meter.calls = 1
    out = await run_agent_test(CONSOLE_GRAPH, "hello", [], client=model, meter=meter)
    assert model.requests == [] and "limit of 1 model calls" in out["response"] and out["error"]


@pytest.mark.asyncio
async def test_the_console_endpoint_records_under_the_application_and_person(project, ledger, monkeypatch):
    from routers import agent_builder
    from schemas.agent_builder import AgentTestRequest
    from services import agent_test_run

    async def refusal(db, **kw):
        return []

    model = Model(input_tokens=50, output_tokens=5)
    real = agent_test_run.run_agent_test

    async def with_fake_model(agent_data, message, history, **kw):
        return await real(agent_data, message, history, client=model, **kw)

    monkeypatch.setattr("services.credits.refusal", refusal)
    monkeypatch.setattr("services.agent_test_run.run_agent_test", with_fake_model)
    out = await agent_builder.test_agent(project.id, "support", AgentTestRequest(message="hi"), USER, None)
    assert out["model_called"] is True
    (row,) = ledger()
    assert (row["project"], row["user"], row["org"], row["agent"]) == ("abc123", "pat@example.com", "org-1", "agent_test")
