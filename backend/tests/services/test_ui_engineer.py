"""The UI engineer: pages as React, accepted only once they compile, and the
floor kept when they never do."""

import json

import pytest

from services.blueprint import ui_engineer
from services.blueprint.agent_contract import apply_agent_result, AgentResult, ArtifactProposal
from services.blueprint.orchestrator import DAG, completed_nodes, pending_subjects
from services.blueprint.service import BlueprintService
from services.blueprint.ui_engineer import CompileError, compose_page, system_prompt

GOOD_VIEW = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
GOOD_LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'


def _doc():
    return {
        "application": {"id": "t", "name": "Desk", "description": "Cases for a hotel."},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Case", "fields": [
            {"name": "title", "type": "string", "required": True}]}]},
        "pages": [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "Every case.",
                   "data": {"primaryEntity": "ENTITY-001"}}],
        "workflows": [],
        "composition": {"vision": "Calm and dense.", "conventions": [{"topic": "header", "rule": "Title left"}]},
    }


class _Client:
    """The writer, and — since the deciding moved into its own call — the
    planner. A plan is answered from the schema it is asked with, so a test
    about the code still lists only code replies."""
    max_tokens = 64000          # a dataclass-less stub: `_with` returns it unchanged

    def __init__(self, replies, plan=None):
        self.replies, self.calls, self.schemas = list(replies), [], []
        self.plan = plan if plan is not None else {
            "state": "None — it renders what load.ts fetched.",
            "sections": ["Header", "Table of cases"],
            "behaviours": ["Empty state reads 'No cases yet'"],
        }

    def __call__(self, *, system, user, schema):
        self.calls.append(user)
        self.schemas.append(schema)
        if "sections" in (schema.get("properties") or {}):
            return json.dumps(self.plan)
        return json.dumps(self.replies.pop(0))

    @property
    def writes(self):
        """The calls that asked for code — the plan is not one of them."""
        return [u for u, sc in zip(self.calls, self.schemas)
                if "load" in (sc.get("properties") or {})]


def test_the_prompt_carries_the_sdk_the_kit_and_the_direction():
    s = system_prompt(_doc())
    assert "export interface Case {" in s                         # this app's entities
    assert "@/components/ui/card" in s and "@tentoroforge/library" in s
    assert "Calm and dense." in s and "header: Title left" in s
    assert "https://" not in s


def test_the_page_is_told_that_its_reply_is_compiled_and_comes_back():
    """It used to be told "it is shipped as you write it", which is not true —
    `compose_page` type-checks every reply and hands the errors back. Believing
    it, the author resolved the whole design before writing a character: on a
    page that IS the application (forge-v3's Calculator, whose direction
    specifies numeric precision, a memory row, AC-versus-C and a 480px
    collapse) that ran to 64,000 tokens of reasoning with no code, twice, and
    the page shipped from its layout instead.

    The claim in the prompt has to keep matching the loop that makes it true."""
    from services.blueprint.ui_engineer import COMPILE_ROUNDS

    s = system_prompt(_doc())
    assert "shipped as you write it" not in s
    assert "WRITE IT, THEN IMPROVE IT" in s
    assert f"up to {COMPILE_ROUNDS} times" in s, "the promise is read off the loop, not retyped"
    assert "begin writing early" in s


def test_a_page_that_compiles_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "List first.", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert body["page"] == "PAGE-001" and body["view"] == GOOD_VIEW
    assert len(client.writes) == 1


def test_the_compilers_errors_go_back_to_the_author(monkeypatch, tmp_path):
    seen = iter([["view.tsx(3,5): error TS2339: Property 'cases' does not exist on type pages."], []])
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: next(seen))
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}] * 2)
    compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert len(client.writes) == 2
    assert "Property 'cases' does not exist" in client.writes[1]
    assert GOOD_VIEW.strip() in client.writes[1], "the retry is shown the code it wrote"


def test_rules_the_compiler_cannot_see_are_refused_too(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    bad = 'export default function View() { return <div style={{ color: "#ff0000" }} />; }'
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": bad}] * ui_engineer.COMPILE_ROUNDS)
    with pytest.raises(CompileError) as e:
        compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert "use client" in str(e.value) and "hex colour" in str(e.value)


def test_the_designed_page_sits_on_its_floor():
    node = DAG["page_code"]
    assert node.optional and node.fanout == "pages"
    assert {"page_layouts", "install", "ui_direction", "workflow_steps"} <= node.depends_on
    assert "page_code" in DAG["frontend"].depends_on
    assert DAG["ui_direction"].optional and DAG["ui_direction"].produces == frozenset({"composition"})
    assert "page_review" not in DAG, "reviewing the pages is the user's Verify & fix, not a build step"


def test_resume_writes_only_the_pages_without_code():
    doc = {"pages": [{"id": "PAGE-001"}, {"id": "PAGE-002"}],
           "pageCode": [{"page": "PAGE-001", "load": "l", "view": "v"}]}
    assert pending_subjects(DAG["page_code"], doc) == ["PAGE-002"]
    assert "page_code" not in completed_nodes(doc)


def test_a_page_code_row_is_accepted_by_the_contract(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "x"}]
    svc.save()
    result = AgentResult(task_id="t", agent="ui_engineer", confidence=0.9, proposals=[ArtifactProposal(
        section="pageCode", natural_key="PAGE-001",
        body={"page": "PAGE-001", "rationale": "r", "load": GOOD_LOAD, "view": GOOD_VIEW})])
    assert apply_agent_result(svc, result).applied
    again = AgentResult(task_id="t2", agent="ui_engineer", confidence=0.9, proposals=[ArtifactProposal(
        section="pageCode", natural_key="PAGE-001",
        body={"page": "PAGE-001", "rationale": "r2", "load": GOOD_LOAD, "view": GOOD_VIEW})])
    apply_agent_result(svc, again)
    assert [r["rationale"] for r in svc.doc["pageCode"]] == ["r2"], "one row per page, replaced"


def test_a_page_that_fails_in_the_finished_app_is_rewritten_or_served_by_its_layout(monkeypatch, tmp_path):
    """Compiled when written, but the finished tree is the one that ships; a page
    that fails there must not ship broken (2g13o6yz's root, 2026-09-19)."""
    from services.blueprint.ui_engineer import settle_code_pages

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/cases", "purpose": "x"},
                        {"id": "PAGE-002", "name": "Other", "route": "/other", "purpose": "x"}]
    svc.doc["pageCode"] = [{"page": p, "load": GOOD_LOAD, "view": GOOD_VIEW} for p in ("PAGE-001", "PAGE-002")]
    svc.save()
    broken = {"PAGE-001", "PAGE-002"}
    monkeypatch.setattr(ui_engineer, "typecheck",
                        lambda doc, root, pid, *a, **k: ["page.tsx(1,1): error TS2554"] if pid in broken else [])
    def rewrite(doc, page, root, client, **kw):
        if page["id"] == "PAGE-002":
            raise CompileError("still broken")
        broken.discard("PAGE-001")
        return {"page": "PAGE-001", "rationale": "fixed", "load": GOOD_LOAD, "view": GOOD_VIEW}, []
    monkeypatch.setattr(ui_engineer, "compose_page", rewrite)
    monkeypatch.setattr("services.blueprint.app_sdk.project_code_pages", lambda doc, root: [])
    out = settle_code_pages(svc, tmp_path / "app", client=object())
    assert out["PAGE-001"] == "rewritten"
    assert out["PAGE-002"].startswith("served by its layout")
    assert [r["page"] for r in svc.doc["pageCode"]] == ["PAGE-001"]


def test_the_reviewer_never_shares_the_persons_build_or_database(monkeypatch, tmp_path):
    """A second `next dev` in the same `.next` broke the person's own server,
    and `start.sh` + `compose stop` moved and then stopped their database."""
    from services.blueprint import page_review

    (tmp_path / ".env.local").write_text("DATABASE_URL=postgresql://postgres:postgres@localhost:5437/app\n")
    assert page_review._database_port(tmp_path) == 5437
    ran, started = [], {}
    monkeypatch.setattr(page_review, "_listening", lambda port: True)          # the person's DB is up
    monkeypatch.setattr(page_review, "_clone_database",
                        lambda root: ("c1", "app_review", "postgresql://x@localhost:5437/app_review"))
    monkeypatch.setattr(page_review.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    class _P:
        pid = 1
        def __init__(self, cmd, **kw): started.update(kw.get("env") or {})
        def wait(self, timeout=None): return 0
    monkeypatch.setattr(page_review.subprocess, "Popen", _P)
    monkeypatch.setattr(page_review.urllib.request, "urlopen", lambda *a, **k: None)
    monkeypatch.setattr(page_review.os, "killpg", lambda *a: None)
    monkeypatch.setattr(page_review.os, "getpgid", lambda pid: pid)
    with page_review.RunningApp(tmp_path):
        pass
    assert started["NEXT_DIST_DIR"] == page_review.REVIEW_DIST_DIR != ".next"
    assert started["DATABASE_URL"].endswith("/app_review"), "clicks never touch the person's data"
    assert "FORGE_REVIEW" not in started, "no flag: the build dir is the signal"
    assert not any("start.sh" in " ".join(c) or "compose" in " ".join(c) for c in ran)
    assert ["docker", "exec", "c1", "dropdb", "-U", "postgres", "--if-exists", "app_review"] in ran


def test_what_the_browser_proves_broken_fails_the_page():
    from services.blueprint.page_review import hard_findings

    shot = {"status": 200, "errors": [],
            "states": {"missing": {"status": 200, "state": "404", "errors": []}},
            "controls": [{"kind": "link", "label": "View", "outcome": "navigated", "detail": "/x"},
                         {"kind": "button", "label": "Export", "outcome": "nothing", "detail": "-"},
                         {"kind": "link", "label": "Annual", "outcome": "broken-link", "detail": "404"},
                         {"kind": "button", "label": "Recalc", "outcome": "error", "detail": "boom"}]}
    hard = hard_findings(shot)
    assert len(hard) == 3, hard                   # a streamed 404 is a 404; a working link is fine
    assert any('"Export" does nothing' in h for h in hard)
    shot["states"]["missing"] = {"status": 200, "state": None, "errors": ["TypeError: x"]}
    assert any("renders as if it did" in h for h in hard_findings(shot))
    assert any("TypeError" in h for h in hard_findings(shot))


def test_a_workflow_launched_from_a_page_must_be_used_by_it():
    from services.blueprint.ui_engineer import _unwired_actions

    doc = _doc()
    doc["workflows"] = [{"id": "FLOW-001", "name": "Close Case", "launchedFrom": ["PAGE-001"]}]
    page = doc["pages"][0]
    assert "Close Case" in _unwired_actions(doc, page, GOOD_VIEW)[0]
    assert _unwired_actions(doc, page, GOOD_VIEW + "\n// <WorkflowButton workflow={workflows.closeCase} />") == []


def test_a_rewrite_that_scores_lower_is_undone(monkeypatch, tmp_path):
    """2g13o6yz's edit page went 7 -> 6 and the worse version stayed."""
    from contextlib import contextmanager
    from services.blueprint import page_review

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Edit", "route": "/cases", "purpose": "x"}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "rationale": "first", "load": GOOD_LOAD, "view": GOOD_VIEW}]
    svc.save()

    class _App:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(page_review, "RunningApp", lambda root: _App())
    monkeypatch.setattr(page_review, "shoot", lambda app, doc, ids, out: [{"id": i, "file": "x"} for i in ids])
    scores = iter([7, 6])
    monkeypatch.setattr(page_review, "critique",
                        lambda doc, page, shot, client: ({"score": next(scores), "verdict": "revise",
                                                          "issues": [], "strengths": [], "broken": []}, None))
    monkeypatch.setattr(ui_engineer, "compose_page", lambda *a, **k: (
        {"page": "PAGE-001", "rationale": "rewrite", "load": GOOD_LOAD, "view": GOOD_VIEW}, []))
    monkeypatch.setattr("services.blueprint.app_sdk.project_code_pages", lambda doc, root: [])
    monkeypatch.setattr(page_review.time, "sleep", lambda s: None)

    out = page_review.review_app(svc, tmp_path / "app", client=object(), rounds=2)
    assert out["pages"]["PAGE-001"]["scores"] == [7, 6]
    assert [r["rationale"] for r in svc.doc["pageCode"]] == ["first"], "the better version is kept"


def test_verify_and_fix_reviews_coded_pages(monkeypatch, tmp_path):
    """The page review is the user's choice after the build: Verify & fix on an
    app with coded pages runs it, scoped, and says what happened."""
    from routers import blueprint_generate as bg
    from services.blueprint import orchestrator

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Cases", "route": "/cases", "purpose": "x"},
                        {"id": "PAGE-002", "name": "Case", "route": "/cases/[id]", "purpose": "x"}]
    svc.doc["pageCode"] = [{"page": p, "load": GOOD_LOAD, "view": GOOD_VIEW} for p in ("PAGE-001", "PAGE-002")]
    svc.save()
    seen = {}
    def review(svc, app_root, *, only=None, emit=None):
        seen["only"] = only
        return {"pages": {"PAGE-001": {"scores": [6, 8], "passed": True, "rewritten": True},
                          "PAGE-002": {"scores": [5], "passed": False, "rewritten": False,
                                       "review": {"broken": ['the button "Export" does nothing']}}}}
    monkeypatch.setattr(orchestrator, "review_coded_pages", review)
    events = []
    bg._run_smith_review(str(tmp_path), str(tmp_path / "app"), emit=lambda k, p: events.append((k, p)),
                         routes=["/cases"])
    assert seen["only"] == {"PAGE-001"}
    said = [p["text"] for k, p in events if k == "message"][-1]
    assert "/cases" in said and "rewrote 1" in said and '"Export" does nothing' in said
    assert ("review", {"phase": "start"}) in events


# ── deciding and writing are two calls ──────────────────────────────────

def test_the_page_is_planned_first_and_the_plan_is_handed_to_the_writer(monkeypatch, tmp_path):
    """Thinking and code come out of one budget, so on a page the Blueprint
    leaves open the deciding took a share nobody chose: the same Calculator
    page, same prompt, same 64,000 tokens, once wrote 3,200 tokens of code,
    once was cut off mid-string, and twice never began. The deciding is now
    asked for on its own, in a budget that cannot swallow the page."""
    from services.blueprint.ui_engineer import PLAN_MAX_TOKENS

    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}],
                     plan={"state": "The expression being typed.",
                           "sections": ["Display", "Keypad"],
                           "behaviours": ["Divide by zero shows Error and keeps the expression"]})
    compose_page(_doc(), _doc()["pages"][0], tmp_path, client)

    assert client.calls[0].startswith("Decide how to build this page")
    assert "do not write it yet" in client.calls[0]
    assert len(client.writes) == 1
    # What it decided arrives as input, so the writing has little left to weigh.
    assert "Divide by zero shows Error" in client.writes[0]
    assert "Your plan for it" in client.writes[0]
    assert PLAN_MAX_TOKENS < 64000, "the plan's budget is what stops the deciding running away"


def test_a_plan_that_fails_still_leaves_a_page(monkeypatch, tmp_path):
    """A plan is a help, never a gate."""
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])

    class _NoPlan(_Client):
        def __call__(self, *, system, user, schema):
            if "sections" in (schema.get("properties") or {}):
                raise RuntimeError("the planner fell over")
            return super().__call__(system=system, user=user, schema=schema)

    client = _NoPlan([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert body["view"] == GOOD_VIEW
    assert "Your plan for it" not in client.writes[0], "written unplanned, as it always was"


def test_a_repair_is_not_planned_again(monkeypatch, tmp_path):
    """The decisions were made and the code exists; what is wanted is a fix."""
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, client,
                 current={"load": GOOD_LOAD, "view": "old"}, feedback="it did not compile")
    assert not any(c.startswith("Decide how to build") for c in client.calls)


def test_the_writing_is_asked_plainly_once_the_deciding_is_done(monkeypatch, tmp_path):
    """Plan at `low` (15s), then write at `low` in 24,000: 64s and a page.
    The same page asked once at `high`/64,000 spent 758s, then 867s, and
    wrote nothing — the budget went on making up its mind."""
    import dataclasses

    from services.blueprint.ui_engineer import PLAN_MAX_TOKENS, WRITE_MAX_TOKENS

    @dataclasses.dataclass
    class _Model:
        effort: str = "high"
        max_tokens: int = 64000
        asked: list = dataclasses.field(default_factory=list)

        def __call__(self, *, system, user, schema):
            self.asked.append((self.effort, self.max_tokens,
                               "plan" if "sections" in (schema.get("properties") or {}) else "write"))
            if "sections" in (schema.get("properties") or {}):
                return json.dumps({"state": "x", "sections": ["a"], "behaviours": ["b"]})
            return json.dumps({"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW})

    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    asked: list = []
    model = _Model(asked=asked)
    compose_page(_doc(), _doc()["pages"][0], tmp_path, model)

    # `dataclasses.replace` makes copies, so every call records into the list
    # they share: the plan, then the writing, each asked in its own budget.
    assert asked == [("low", PLAN_MAX_TOKENS, "plan"), ("low", WRITE_MAX_TOKENS, "write")]
    assert WRITE_MAX_TOKENS < 64000 and PLAN_MAX_TOKENS < WRITE_MAX_TOKENS
