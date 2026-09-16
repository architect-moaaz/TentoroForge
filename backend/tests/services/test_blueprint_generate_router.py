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
    same courtesy, because the definition is cheap and the DAG is not.

    Asserted against `domain_nodes` rather than the node names spelled out
    here. The gate is one fact about the lifecycle and it was written down in
    three places — this route, the Smith turn path, and `_run_dag` — which is
    two more than can be kept in agreement. A test that greps for the literal
    is a test that pins the duplication in place.
    """
    import inspect

    from routers import blueprint_generate
    from services.smith.smith import domain_nodes

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert "define_only" in src and "domain_nodes()" in src
    assert domain_nodes() == ["requirements", "application_model"]


def test_every_path_into_the_dag_uses_the_same_definition_of_the_gate():
    """`generate_via_blueprint` and `_run_dag` are two doors into §28's graph,
    and both decide what "not approved yet" runs. They have to agree."""
    import inspect

    from routers import blueprint_generate

    for fn in (blueprint_generate.generate_via_blueprint,
               blueprint_generate._run_dag):
        src = inspect.getsource(fn)
        assert "domain_nodes()" in src, fn.__name__
        assert '"application_model"' not in src, fn.__name__


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


def test_a_resumed_description_goes_where_the_contract_allows(tmp_path):
    """`product` holds objectives, personas, terminology and capabilities and
    admits nothing else; the description belongs on `application`.

    Writing it to the wrong section poisoned the document with a field the
    contract refuses. `save()` does not validate, so it reached disk, and every
    resumed run then failed on the first validate — the requirements node died
    and all twenty-one nodes behind it were skipped.
    """
    from services.blueprint.service import BlueprintService

    svc = _seed(tmp_path)
    svc.doc.setdefault("application", {})["description"] = "restated intent"
    svc.validate()          # the section the router writes to must be legal

    svc.doc.setdefault("product", {})["description"] = "wrong section"
    import pytest
    with pytest.raises(Exception):
        svc.validate()


def test_the_router_validates_before_it_persists():
    import inspect

    from routers import blueprint_generate

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert '"application", {})["description"]' in src
    assert "svc.validate()" in src, (
        "an invalid document must not reach disk — save() does not check")


def test_a_bare_post_stops_at_the_definition(tmp_path):
    """§25 — 'once the application definition is accepted, Smith generates the
    build plan.' Without a checkpoint one POST spends forty minutes and a dozen
    model calls on an understanding nobody has looked at."""
    import inspect

    from routers import blueprint_generate

    assert blueprint_generate.BlueprintGenerateRequest(
        description="x").approved is False

    src = inspect.getsource(blueprint_generate.generate_via_blueprint)
    assert "not req.approved" in src
    assert "awaitingApproval" in src, "the client has to know it is being asked"


def test_the_plan_forecasts_what_should_exist(tmp_path):
    """§26's plan is counts, not an order. A node list says what will happen;
    a forecast says what should exist afterwards, and only the second can be
    checked against the result."""
    from services.blueprint.plan_forecast import forecast, render

    doc = {
        "requirements": [{"id": "REQ-001"}],
        "pages": [{"id": "PAGE-001"}, {"id": "PAGE-002"}],
        "data": {"entities": [{"id": "ENTITY-001"}]},
        "workflows": [{"id": "FLOW-001"}],
        "businessRules": [], "apis": [], "roles": [], "integrations": [],
    }
    f = forecast(doc)
    assert f["pages"] == 2 and f["entities"] == 1
    # 2 pages x 2 + 1 workflow x 3
    assert f["expectedTests"] == 7
    assert "2 pages" in render(f)


def test_deprecated_artifacts_are_not_forecast(tmp_path):
    from services.blueprint.plan_forecast import forecast

    doc = {"pages": [{"id": "P1"}, {"id": "P2", "status": "DEPRECATED"}]}
    assert forecast(doc)["pages"] == 1


def test_the_forecast_is_compared_to_the_outcome(tmp_path):
    """Reported, not enforced: nineteen pages where eighteen were forecast has
    not failed. Two has."""
    from services.blueprint.plan_forecast import compare, forecast

    planned = forecast({"pages": [{"id": f"P{i}"} for i in range(18)]})
    thin = {"pages": [{"id": "P1"}, {"id": "P2"}]}
    drift = compare(planned, thin)
    assert drift["pages"] == {"planned": 18, "actual": 2, "delta": -16}

    assert compare(planned, {"pages": [{"id": f"P{i}"} for i in range(18)]}) == {}



# --- the verify-&-fix offer reaches the user -------------------------------
#
# The offer used to be emitted by the caller AFTER `_run_dag` returned. A build
# that outran its turn released the panel, finished in the background, announced
# completion, and the offer — emitted later with the stream gone and nothing
# persisting it — never arrived. Measured on a real build (roazgziv): the
# "your application is built" line was in the transcript, the offer was not.
# It now rides the completion announcement: one helper, one emit, both persisted.

def test_the_verify_offer_rides_the_completion_announcement(monkeypatch):
    from routers import blueprint_generate as bg
    monkeypatch.setattr(bg, "_build_complete_message",
                        lambda doc: "Your application is built — 2 pages ready.")
    events: list[tuple[str, dict]] = []
    bg._announce_build_complete({"pages": []},
                                lambda ev, data: events.append((ev, data)),
                                offer_verify=True, where="t")
    msgs = [d for e, d in events if e == "message"]
    assert msgs[0]["text"].startswith("Your application is built")
    offer = [m for m in msgs if m.get("options")]
    assert offer and offer[0]["options"] == list(bg._VERIFY_OFFER_OPTIONS)
    assert offer[0]["status"] == "asked"


def test_the_standalone_build_makes_no_verify_offer(monkeypatch):
    # `/generate/blueprint` (offer_verify=False) announces completion but does
    # not offer to verify — the offer belongs to the Smith chat turn.
    from routers import blueprint_generate as bg
    monkeypatch.setattr(bg, "_build_complete_message",
                        lambda doc: "Your application is built — 2 pages ready.")
    events: list[tuple[str, dict]] = []
    bg._announce_build_complete({"pages": []},
                                lambda ev, data: events.append((ev, data)),
                                offer_verify=False, where="t")
    msgs = [d for e, d in events if e == "message"]
    assert len(msgs) == 1 and not msgs[0].get("options")


def test_nothing_built_announces_nothing_and_offers_nothing(monkeypatch):
    from routers import blueprint_generate as bg
    monkeypatch.setattr(bg, "_build_complete_message", lambda doc: None)
    events: list[tuple[str, dict]] = []
    bg._announce_build_complete({}, lambda ev, data: events.append((ev, data)),
                                offer_verify=True, where="t")
    assert events == []


def test_the_offered_option_is_the_consent_the_next_turn_accepts():
    # The loop closes: the exact option Smith offers is what `_is_verify_consent`
    # recognises when the user clicks it (the frontend sends the label back).
    from routers import blueprint_generate as bg
    assert bg._is_verify_consent(bg._VERIFY_OFFER_OPTIONS[0]) is True
    assert bg._is_verify_consent(bg._VERIFY_OFFER_OPTIONS[1]) is False


# --- the Verify & Fix chip's own sentences are consent; questions are not -----

def test_the_chips_sentences_are_taken_as_consent():
    import routers.blueprint_generate as bg
    for m in ("Verify the app and fix anything that's broken.",
              "Verify only the current page: /master-data",
              "Verify only the critical journeys.",
              "verify and fix", "Verify & fix"):
        assert bg._is_verify_consent(m) is True, m
    for m in ("did you verify it?", "have you verified the login page",
              "can you verify my email format is right", "no, not now",
              "I want to add a verify step to the workflow", ""):
        assert bg._is_verify_consent(m) is False, m


def test_the_current_page_scope_is_a_route_list():
    import routers.blueprint_generate as bg
    assert bg._verify_scope("Verify only the current page: /master-data") == ["/master-data"]
    assert bg._verify_scope("verify only the current page /admin/foo.") == ["/admin/foo"]
    assert bg._verify_scope("Verify the app and fix anything that's broken.") is None
    assert bg._verify_scope("Verify only the critical journeys.") is None


def test_the_chat_request_carries_the_supplied_documents_into_the_brief():
    """A-03/B-08: the requirements file attached on /blueprint/new is read in
    the browser and posted with the first turn. It reached only the legacy
    generate request; the panel posts to smith/chat, which dropped it."""
    from routers.blueprint_generate import SmithChatRequest, _brief_with_documents
    req = SmithChatRequest(message="a clinic visit tracker", evidence=["1. Reception registers a patient."])
    assert req.evidence == ["1. Reception registers a patient."]
    brief = _brief_with_documents("a clinic visit tracker", req.evidence)
    assert brief.startswith("a clinic visit tracker") and "SUPPLIED DOCUMENTS" in brief
    assert "--- document 1 ---\n1. Reception registers a patient." in brief
    assert _brief_with_documents("x", []) == "x" and _brief_with_documents("x", ["  "]) == "x"


def test_a_credential_is_taken_out_before_the_turn_is_written_down():
    """§42: chat history is the first place a raw credential must not rest.
    The extracted FIELD was already dropped, so a token never reached the
    Blueprint — but the message was stored exactly as typed, which put it on
    disk and handed it back to every later turn."""
    from services.smith.secrets_scrub import MASK, carries_secret, scrub

    assert scrub("use figd_abcdefghij1234567890 please").startswith("use " + MASK)
    assert MASK in scrub("my key is SG.abcdefghij.klmnopqrstuv")
    assert scrub("password: hunter2000") == "password: " + MASK
    assert MASK in scrub("Authorization: Bearer sk-ant-abcdefghijklmnop1234")
    # A NAME IS NOT A SECRET — it is the thing Smith asks for.
    for kept in ("set SENDGRID_API_KEY in the environment",
                 "the API_KEY = SENDGRID_API_KEY variable",
                 "add a phone number to nurses",
                 "call the app Nurse Roster"):
        assert scrub(kept) == kept and not carries_secret(kept)
    assert scrub("") == "" and scrub(None) == ""
    # Idempotent: scrubbing what is already scrubbed changes nothing.
    once = scrub("token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijkl")
    assert scrub(once) == once


def test_the_lifecycle_words_are_answered_where_they_are_typed(tmp_path):
    """`preview`, `export` and `deploy` were declared lifecycle verbs with no
    branch, so the architect took them as changes: "preview" came back
    refusing a build on a stale approval and "export" asked what kind."""
    from routers.blueprint_generate import (_deploy_refusal, _export_report,
                                            _lifecycle_verb, _preview_report)

    doc = {"pages": [{"route": "/master-data", "id": "PAGE-001"},
                     {"route": "/gone", "id": "PAGE-002", "status": "DEPRECATED"}]}
    assert "Nothing to look at yet" in _preview_report(doc, tmp_path)
    assert "nothing to export yet" in _export_report(tmp_path)

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    built = _preview_report(doc, tmp_path)
    assert "`/master-data`" in built and "/gone" not in built
    assert "Export" in _export_report(tmp_path)
    # Publishing is never done from a typed sentence.
    said = _deploy_refusal()
    assert "not something I do from a typed sentence" in said and "export" in said
    # Only an exact one-word command is the verb.
    assert _lifecycle_verb("preview") == "preview"
    assert _lifecycle_verb("preview the nurses page") is None


def test_the_go_ahead_to_build_is_the_whole_message_not_a_word_in_it():
    """"Build it" typed by a layman was answered with a description of a card
    to press. It is a door now — but "build a dashboard" is still a screen to
    compose, so the consent has to BE the message."""
    from routers.blueprint_generate import _is_build_consent

    for said in ("build", "build it", "Build it.", "go on then", "do it",
                 "make it", "yes, build it", "approve and build", "PROCEED"):
        assert _is_build_consent(said), said
    for said in ("build a dashboard", "build a page for reports",
                 "rebuild the nurses page", "do it after the phone number",
                 "", "   "):
        assert not _is_build_consent(said), said


def test_a_typed_verify_is_told_what_it_costs_and_asked_how_much():
    """The chip asks the scope; a typed "verify" named none and ran the whole
    application — fifteen to twenty-five minutes of composing."""
    from routers.blueprint_generate import (_DECLINED, _VERIFY_SCOPES,
                                            _is_verify_consent,
                                            _scope_was_chosen,
                                            _verify_scope_question)

    doc = {"pages": [{"route": f"/p{i}"} for i in range(8)]}
    said = _verify_scope_question(doc)
    assert "fifteen to twenty-five minutes" in said and "8 screen(s)" in said
    assert said.rstrip().endswith("How much should I look at?")
    # Small applications are not told a big number.
    assert "several minutes" in _verify_scope_question({"pages": [{"route": "/a"}]})

    # A bare consent has no scope, so it is asked; an answer to the question
    # is not asked again.
    assert _is_verify_consent("verify") and not _scope_was_chosen("verify")
    for scope in _VERIFY_SCOPES[:2]:
        assert _scope_was_chosen(scope), scope
    # Turning it down is an answer, not a change to interpret.
    assert "not now" in _DECLINED and "no thanks" in _DECLINED
    assert not _is_verify_consent("Not now")
