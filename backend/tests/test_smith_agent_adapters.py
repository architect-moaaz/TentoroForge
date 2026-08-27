"""Narrator-mode agent adapters — Migration Step 1.

These wrap the existing agent functions (`run_discovery`, `run_planner`,
`run_code_generator`) and normalize their outputs into
DiscoveryArtifact / PlannerArtifact / GeneratorArtifact.

Tests cover the normalization layer with mocked agent outputs. Real
LLM calls happen at wire-in time (Step 3+); the adapters themselves
are pure normalization + orchestration seams.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_agent_adapters import (
    plan_dict_to_artifact,
    discovery_stream_to_artifact,
    generator_files_to_artifact,
)
from services.narrator_artifacts import (
    DiscoveryArtifact, PlannerArtifact, GeneratorArtifact,
    NarratorArtifactError,
)


# --------------------------------------------------------------------------- #
# plan_dict_to_artifact — the shape run_planner_oneshot returns
# --------------------------------------------------------------------------- #

def test_plan_dict_to_artifact_maps_models_to_entities():
    """run_planner returns plans with `models` (entities) + `pages` +
    `workflows`. Adapter renames + normalizes."""
    plan = {
        "models": [
            {"name": "Candidate",
             "fields": [
                 {"name": "email", "type": "varchar", "notNull": True},
                 {"name": "firstName", "type": "varchar"},
             ]},
        ],
        "workflows": [
            {"name": "CreateCandidate", "trigger": {"type": "form"}},
        ],
        "pages": [
            {"route": "/candidates", "type": "list"},
        ],
    }
    art = plan_dict_to_artifact(plan)
    assert len(art.entities) == 1
    assert art.entities[0].name == "Candidate"
    assert "email" in art.entities[0].key_fields
    assert len(art.workflows) == 1
    assert len(art.pages) == 1


def test_plan_dict_to_artifact_derives_schema_path_from_route():
    """The planner emits routes; the schema path convention is
    src/schemas/<slug>[/subpath].json. Adapter fills it in when
    the plan didn't."""
    plan = {
        "models": [{"name": "X", "fields": []}],
        "pages": [{"route": "/candidates/new", "type": "form"}],
    }
    art = plan_dict_to_artifact(plan)
    assert art.pages[0].schema_path.endswith("candidates/new.json")


def test_plan_dict_to_artifact_raises_on_empty_plan():
    with pytest.raises(NarratorArtifactError):
        plan_dict_to_artifact({"models": [], "pages": []})


# --------------------------------------------------------------------------- #
# discovery_stream_to_artifact — extracts the ```discovery-brief``` block
# --------------------------------------------------------------------------- #

def test_discovery_stream_extracts_json_from_discovery_brief_block():
    """run_discovery yields streaming Messages; the last assistant
    turn contains a ```discovery-brief JSON block. Adapter accumulates
    text from the stream and parses it."""
    accumulated_text = (
        "Let me think about this...\n"
        "```discovery-brief\n"
        + json.dumps({
            "domain_name": "Cabin Crew ATS",
            "actors": ["recruiter", "candidate"],
            "verbs": ["apply", "schedule"],
            "distinctive_shape": "kanban pipeline",
            "proposed_entities": [{"name": "Candidate", "why": "the applicant"}],
            "open_questions": ["how are assessments scheduled?"],
            "confidence": 0.9,
        })
        + "\n```\n"
    )
    art = discovery_stream_to_artifact(accumulated_text)
    assert art.domain_name == "Cabin Crew ATS"
    assert art.actors == ["recruiter", "candidate"]
    assert art.proposed_entities[0].name == "Candidate"
    assert art.confidence == 0.9


def test_discovery_stream_missing_brief_raises_clearly():
    text = "just some prose with no brief block anywhere"
    with pytest.raises(NarratorArtifactError):
        discovery_stream_to_artifact(text)


def test_discovery_stream_malformed_json_raises_clearly():
    text = "```discovery-brief\n{not valid json\n```"
    with pytest.raises(NarratorArtifactError):
        discovery_stream_to_artifact(text)


# --------------------------------------------------------------------------- #
# generator_files_to_artifact — reads what was written to disk
# --------------------------------------------------------------------------- #

def test_generator_files_to_artifact_lists_files_under_output_dir(tmp_path):
    """Enumerates every file under `output_dir` that looks generated
    (skips .git, node_modules, .next). Warnings + notes are optional
    inputs the caller supplies from pipeline logs."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "a.json").write_text("{}")
    (tmp_path / "src" / "schemas" / "b.json").write_text("{}")
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "X.json").write_text("{}")
    # Junk dirs must be ignored.
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("junk")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "leftpad.js").write_text("junk")

    art = generator_files_to_artifact(
        output_dir=str(tmp_path),
        warnings=["form_scaffold: added 2 fields"],
        notes=["seed_synthesizer: 60 rows"],
    )
    assert isinstance(art, GeneratorArtifact)
    files_set = set(art.generated_files)
    assert "src/schemas/a.json" in files_set
    assert "src/schemas/b.json" in files_set
    assert "workflows/X.json" in files_set
    # Junk stayed out.
    assert not any(".git" in f for f in files_set)
    assert not any("node_modules" in f for f in files_set)
    # Warnings/notes preserved.
    assert "form_scaffold" in art.warnings[0]
    assert "seed_synthesizer" in art.notes[0]


def test_generator_files_to_artifact_missing_dir_returns_empty(tmp_path):
    art = generator_files_to_artifact(
        output_dir=str(tmp_path / "does-not-exist"),
    )
    assert art.generated_files == []
    assert art.warnings == []


# --------------------------------------------------------------------------- #
# Live orchestrators — Phase B
# --------------------------------------------------------------------------- #

import asyncio


def _make_msg_with_text(text: str):
    """Minimal Message-shaped stand-in with .content=[{.text: str}]."""
    class _Block:
        def __init__(self, t): self.text = t
    class _Msg:
        def __init__(self, t): self.content = [_Block(t)]
    return _Msg(text)


async def _async_iter(items):
    for i in items:
        yield i


def test_orchestrate_discovery_wraps_domain_agent_and_normalizes(
    tmp_path, monkeypatch,
):
    """orchestrate_discovery calls run_domain_discovery (single-shot,
    returns dict) and translates the domain-agent dossier shape into
    a DiscoveryArtifact. Preserves raw dossier as _raw_dossier."""
    from services import smith_agent_adapters as adapters

    domain_dossier = {
        "domain": "ATS",
        "confidence": 0.9,
        "personas": {"planner": "senior recruiter"},
        "designPatterns": [
            {"name": "Kanban pipeline", "description": "Drag candidates through stages"},
            {"name": "Interview scheduler", "description": "Calendar slot picker"},
        ],
        "entitySuggestions": [
            {"name": "Candidate", "likelyFields": ["email", "resume_url", "stage"]},
            {"name": "Interview", "likelyFields": ["candidate_id", "slot"]},
        ],
        "uncertainAreas": ["how are assessments scheduled?"],
        "complianceNotes": ["gdpr"],
        "source": "domain_agent",
    }

    async def _fake_domain_discovery(description, plan=None, *, enable_web_search=True, **kw):
        return domain_dossier
    monkeypatch.setattr(
        "agents.domain_agent.run_domain_discovery",
        _fake_domain_discovery,
    )

    art = asyncio.run(adapters.orchestrate_discovery(
        output_dir=str(tmp_path), user_message="build me an ATS",
    ))
    assert art.domain_name == "ATS"
    assert art.confidence == 0.9
    assert {e.name for e in art.proposed_entities} == {"Candidate", "Interview"}
    assert "email" in art.proposed_entities[0].why
    assert art.open_questions == ["how are assessments scheduled?"]
    assert "Kanban" in art.distinctive_shape
    # actors/verbs — domain agent doesn't carry these, adapter leaves empty
    assert art.actors == []
    assert art.verbs == []
    # Raw dossier preserved on the artifact for downstream consumers
    raw = getattr(art, "_raw_dossier", None)
    assert isinstance(raw, dict)
    assert raw["complianceNotes"] == ["gdpr"]
    assert raw["personas"]["planner"] == "senior recruiter"


def test_orchestrate_discovery_raises_when_domain_missing(
    tmp_path, monkeypatch,
):
    from services import smith_agent_adapters as adapters
    from services.narrator_artifacts import NarratorArtifactError

    async def _fake_domain_discovery(description, plan=None, **kw):
        return {"domain": "", "confidence": 0.5}  # empty domain — can't narrate
    monkeypatch.setattr(
        "agents.domain_agent.run_domain_discovery",
        _fake_domain_discovery,
    )
    with pytest.raises(NarratorArtifactError):
        asyncio.run(adapters.orchestrate_discovery(
            output_dir=str(tmp_path), user_message="x",
        ))


def test_orchestrate_planner_wraps_oneshot_and_normalizes(monkeypatch):
    """Critic disabled — first-draft plan flows through unchanged."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")
    from services import smith_agent_adapters as adapters

    fake_plan = {
        "models": [{"name": "Candidate", "fields": [{"name": "email"}]}],
        "workflows": [{"name": "CreateCandidate"}],
        "pages": [{"route": "/candidates", "type": "list"}],
    }

    async def _fake_oneshot(description, domain_context=None, *, timeout_seconds=300.0, prior_plan=None, emit_fn=None, **_kw):
        return fake_plan

    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    art = asyncio.run(adapters.orchestrate_planner(
        description="Build me an ATS", domain_context={"domain": "hiring"},
    ))
    assert len(art.entities) == 1
    assert art.entities[0].name == "Candidate"
    assert art.workflows[0].name == "CreateCandidate"


# --------------------------------------------------------------------------- #
# Actor-Critic loop — orchestrate_planner
# --------------------------------------------------------------------------- #

def _make_plan(name="X"):
    return {
        "models": [{"name": name, "fields": [{"name": "id"}]}],
        "workflows": [], "pages": [{"route": f"/{name.lower()}", "type": "list"}],
    }


def _critic_verdict(verdict="approve", blockers=0, important=0, domain="Test"):
    """Build a critic-reply dict matching agents.plan_critic.critique_plan
    output shape."""
    gaps = []
    for _ in range(blockers):
        gaps.append({"severity": "blocker", "lens": "domain",
                     "dimension": "entities", "suggestion": "add X",
                     "evidence": "…", "confidence": 0.9})
    for _ in range(important):
        gaps.append({"severity": "important", "lens": "arch",
                     "dimension": "workflows", "suggestion": "add Y",
                     "evidence": "…", "confidence": 0.7})
    return {
        "inferred_domain": domain, "inferred_confidence": 0.9,
        "scores": {"entities": 4, "relationships": 4, "workflows": 4,
                   "user_journeys": 4, "data_integrity": 4},
        "verdict": verdict, "gaps": gaps,
        "future_considerations": [], "kept": [], "raw_reply": "",
    }


def test_orchestrate_planner_critic_approves_turn_1(monkeypatch):
    """Critic approves on the first turn — one planner call total."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    planner_calls = []
    async def _fake_oneshot(description, domain_context=None, *, timeout_seconds=300.0, prior_plan=None, emit_fn=None, **_kw):
        planner_calls.append(description)
        return _make_plan("Candidate")
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    async def _fake_critique(**kwargs):
        return _critic_verdict(verdict="approve")
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    art = asyncio.run(adapters.orchestrate_planner(
        description="Build ATS", domain_context={"domain": "hiring"},
    ))
    assert art.entities[0].name == "Candidate"
    assert len(planner_calls) == 1  # no retries after approve


def test_orchestrate_planner_critic_revises_then_approves(monkeypatch):
    """Turn 1 revise (2 blockers) → planner called again → turn 2 approve."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    plans = [_make_plan("V1"), _make_plan("V2")]
    call_i = {"n": 0}
    async def _fake_oneshot(description, domain_context=None, *, timeout_seconds=300.0, prior_plan=None, emit_fn=None, **_kw):
        p = plans[call_i["n"]]
        call_i["n"] += 1
        return p
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    verdicts = [
        _critic_verdict(verdict="revise", blockers=2),
        _critic_verdict(verdict="approve"),
    ]
    turn = {"n": 0}
    async def _fake_critique(**kwargs):
        v = verdicts[turn["n"]]
        turn["n"] += 1
        return v
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    art = asyncio.run(adapters.orchestrate_planner(
        description="Build ATS", domain_context={"domain": "hiring"},
    ))
    assert art.entities[0].name == "V2"  # revised plan won
    assert call_i["n"] == 2


def test_orchestrate_planner_critic_reject_short_circuits(monkeypatch):
    """Reject on turn 1 → ship best-so-far (only candidate)."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    call_i = {"n": 0}
    async def _fake_oneshot(description, *args, **kwargs):
        call_i["n"] += 1
        return _make_plan("Draft")
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    async def _fake_critique(**kwargs):
        return _critic_verdict(verdict="reject", blockers=5)
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    art = asyncio.run(adapters.orchestrate_planner(
        description="Build X", domain_context={"domain": "hiring"},
    ))
    assert art.entities[0].name == "Draft"
    assert call_i["n"] == 1  # never retried


def test_orchestrate_planner_critic_cap_ships_best_so_far(monkeypatch):
    """3 turns of revise → cap → ship the plan with fewest blockers."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    plans = [_make_plan("V1"), _make_plan("V2"), _make_plan("V3")]
    call_i = {"n": 0}
    async def _fake_oneshot(description, *args, **kwargs):
        p = plans[call_i["n"]]
        call_i["n"] += 1
        return p
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    # V1 has 3 blockers, V2 has 1, V3 has 2 → V2 should win.
    verdicts = [
        _critic_verdict(verdict="revise", blockers=3),
        _critic_verdict(verdict="revise", blockers=1),
        _critic_verdict(verdict="revise", blockers=2),
    ]
    turn = {"n": 0}
    async def _fake_critique(**kwargs):
        v = verdicts[turn["n"]]
        turn["n"] += 1
        return v
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    art = asyncio.run(adapters.orchestrate_planner(
        description="Build X", domain_context={"domain": "hiring"},
    ))
    assert art.entities[0].name == "V2"  # fewest blockers wins


def test_orchestrate_planner_critic_merge_preserves_unchanged_sections(monkeypatch):
    """Real-world bug: LLM revisions after critic feedback sometimes
    drop entire sections (data_models, access_control). Merge must
    preserve them from the prior plan so the final plan is complete."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    # Turn 0: full plan
    full_plan = {
        "module_name": "ats",
        "description": "Cabin crew ATS",
        "data_models": [{"name": "Candidate", "fields": [{"name": "email", "type": "text"}]}],
        "access_control": {"roles": ["Recruiter", "Admin"], "rules": ["Recruiter can only see own drives"]},
        "workflows": [{"name": "OldWF", "steps": [{"name": "s1"}]}],
        "pages": [{"route": "/candidates", "name": "List", "description": "Applicant list"}],
    }
    # Turn 1 revision: LLM only emitted the workflows change — dropped
    # data_models, access_control, description entirely.
    partial_revision = {
        "workflows": [{"name": "NewWF", "steps": [{"name": "s1"}]}],
    }
    plans_returned = [full_plan, partial_revision]
    call_i = {"n": 0}
    async def _fake_oneshot(description, *args, **kwargs):
        p = plans_returned[call_i["n"]]
        call_i["n"] += 1
        return p
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    verdicts = [
        _critic_verdict(verdict="revise", blockers=1),
        _critic_verdict(verdict="approve"),
    ]
    turn = {"n": 0}
    async def _fake_critique(**kwargs):
        v = verdicts[turn["n"]]
        turn["n"] += 1
        return v
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    art = asyncio.run(adapters.orchestrate_planner(
        description="x", domain_context={"domain": "hiring"},
    ))
    raw = getattr(art, "_raw_plan", None)
    assert raw is not None
    # Revised sections landed
    assert raw["workflows"][0]["name"] == "NewWF"
    # Dropped-by-LLM sections preserved from prior
    assert raw["data_models"][0]["name"] == "Candidate"
    assert raw["access_control"]["roles"] == ["Recruiter", "Admin"]
    assert raw["description"] == "Cabin crew ATS"
    assert raw["module_name"] == "ats"
    assert raw["pages"][0]["description"] == "Applicant list"


def test_orchestrate_planner_emit_fn_receives_critic_events(monkeypatch):
    """Optional emit_fn is called for critic_start/turn_start/verdict/approved."""
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "1")
    from services import smith_agent_adapters as adapters

    async def _fake_oneshot(description, *args, **kwargs): return _make_plan("Approved")
    monkeypatch.setattr("agents.planner.run_planner_oneshot", _fake_oneshot)

    async def _fake_critique(**kwargs): return _critic_verdict(verdict="approve")
    monkeypatch.setattr("agents.plan_critic.critique_plan", _fake_critique)

    events: list[tuple[str, dict]] = []
    def _emit(stage, payload): events.append((stage, payload))

    asyncio.run(adapters.orchestrate_planner(
        description="Build", domain_context=None, emit_fn=_emit,
    ))
    stages = [s for s, _ in events]
    assert "critic_start" in stages
    assert "critic_turn_start" in stages
    assert "critic_verdict" in stages
    assert "critic_approved" in stages


def test_orchestrate_generator_snapshot_is_a_pure_snapshot(tmp_path):
    """The generator adapter doesn't RUN the pipeline — it snapshots
    the file tree left behind + accepts caller warnings/notes."""
    from services import smith_agent_adapters as adapters

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.json").write_text("{}")

    art = adapters.orchestrate_generator_snapshot(
        output_dir=str(tmp_path),
        warnings=["form_scaffold added 2 fields"],
        notes=["seed_synthesizer: 60 rows"],
    )
    assert "src/a.json" in art.generated_files
    assert art.warnings == ["form_scaffold added 2 fields"]
    assert art.notes == ["seed_synthesizer: 60 rows"]


# --------------------------------------------------------------------------- #
# orchestrate_generation — Smith invokes the pipeline as his tool
# --------------------------------------------------------------------------- #

def test_orchestrate_generation_brackets_pipeline_with_narrations(tmp_path, monkeypatch):
    """Smith opens with narration, forwards every pipeline event,
    closes with narration. Fallback prose used when no API key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from services import smith_agent_adapters as adapters

    async def _fake_pipeline(**kwargs):
        yield {"type": "phase", "data": {"name": "schema"}}
        yield {"type": "phase", "data": {"name": "pages"}}
        yield {"type": "complete", "data": {}}

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.json").write_text("{}")

    async def _collect():
        events = []
        async for e in adapters.orchestrate_generation(
            pipeline_fn=_fake_pipeline,
            output_dir=str(tmp_path),
            project_id="p1",
            plan={"models": [{"name": "X"}]},
            description="build me an ATS",
            user_ask="build me an ATS",
        ):
            events.append(e)
        return events

    events = asyncio.run(_collect())
    # First = OPEN narration — SSE dict shape ({event, data:json-string})
    assert events[0]["event"] == "smith_narration"
    open_data = json.loads(events[0]["data"])
    assert open_data["stage"] == "generation_handoff"
    # Middle = pipeline events, unchanged (fake uses "type" — passed through)
    assert events[1]["type"] == "phase"
    assert events[-2]["type"] == "complete"
    # Last = CLOSE narration
    assert events[-1]["event"] == "smith_narration"
    close_data = json.loads(events[-1]["data"])
    assert close_data["stage"] == "generation_complete"
    assert close_data["files_count"] == 1
    assert close_data["error"] is None


def test_orchestrate_generation_pipeline_error_emits_close_and_reraises(tmp_path, monkeypatch):
    """When the pipeline raises, orchestrate_generation still emits
    the CLOSE narration (with error) THEN re-raises. Callers get
    both signals — the log entry AND the exception."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from services import smith_agent_adapters as adapters

    class _Boom(RuntimeError):
        pass

    async def _crashing_pipeline(**kwargs):
        yield {"type": "phase", "data": {"name": "schema"}}
        raise _Boom("agent SDK died")

    async def _drive():
        events = []
        with pytest.raises(_Boom):
            async for e in adapters.orchestrate_generation(
                pipeline_fn=_crashing_pipeline,
                output_dir=str(tmp_path),
                project_id="p1",
                plan={"models": [{"name": "X"}]},
                description="build",
            ):
                events.append(e)
        return events

    events = asyncio.run(_drive())
    # OPEN + 1 phase + CLOSE = 3 events before raise
    assert events[0]["event"] == "smith_narration"
    open_data = json.loads(events[0]["data"])
    assert open_data["stage"] == "generation_handoff"
    assert events[1]["type"] == "phase"
    assert events[-1]["event"] == "smith_narration"
    close_data = json.loads(events[-1]["data"])
    assert close_data["stage"] == "generation_complete"
    assert "_Boom" in close_data["error"]


def test_orchestrate_generation_passes_kwargs_through(tmp_path, monkeypatch):
    """Every kwarg the pipeline function needs is forwarded verbatim."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from services import smith_agent_adapters as adapters

    captured = {}
    async def _pipeline(**kwargs):
        captured.update(kwargs)
        yield {"type": "complete", "data": {}}
        return

    async def _drive():
        async for _ in adapters.orchestrate_generation(
            pipeline_fn=_pipeline,
            output_dir=str(tmp_path),
            project_id="p42",
            plan={"models": []},
            description="hi",
            figma_context={"foo": "bar"},
            domain_context={"domain": "hiring"},
        ):
            pass
    asyncio.run(_drive())
    assert captured["output_dir"] == str(tmp_path)
    assert captured["project_id"] == "p42"
    assert captured["plan"] == {"models": []}
    assert captured["description"] == "hi"
    assert captured["figma_context"] == {"foo": "bar"}
    assert captured["domain_context"] == {"domain": "hiring"}
