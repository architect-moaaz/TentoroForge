"""What ecom v2's first two features showed (forge-v3, 2026-10-10):

- every Vendor a statement tried to make answered HTTP 500
  "SENSITIVE_ENCRYPTION_KEY is not set", so 16 of 17 statements went untried —
  the key is the app's, made with it and proven at the Workbench's door;
- a given record told apart by its name kept its slug, the app answered 409
  CONFLICT, and the statement failed as the app's;
- a fix turn the engineer started ran out of steps saying "the categories
  screen is already working correctly" over its own failing try.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

from services import workbench
from services.auth_secret import ensure_sensitive_key, sensitive_key


def test_an_app_gets_a_key_for_its_sensitive_columns_once(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "package.json").write_text("{}")
    (root / ".env.local").write_text("DATABASE_URL=postgresql://x\nNEXTAUTH_SECRET=abc\n")
    assert ensure_sensitive_key(root) == {"set": True}
    key = sensitive_key(root)
    assert len(base64.b64decode(key)) == 32, "the AES-256 key the runtime expects"
    assert ensure_sensitive_key(root) == {"set": False} and sensitive_key(root) == key, "kept: rows depend on it"
    assert "DATABASE_URL=postgresql://x" in (root / ".env.local").read_text()
    bare = tmp_path / "bare"
    bare.mkdir()
    assert ensure_sensitive_key(bare)["set"] and sensitive_key(bare), "written even where no .env.local was"


def test_the_workbench_proves_the_secrets_before_the_database(monkeypatch, tmp_path):
    from services.blueprint.assembly import INSTALLED_MARK
    root = tmp_path / "app"
    root.mkdir()
    (root / "package.json").write_text("{}")
    (root / "node_modules").mkdir()
    (root / "node_modules" / INSTALLED_MARK).write_text("npm install finished\n")
    (root / ".env.local").write_text("NEXTAUTH_SECRET=dev-secret-change-me-in-production\n")
    monkeypatch.setattr(workbench, "_database",
                        lambda r: {"schema": {"ok": True, "did": ""}, "seeded": {"ok": True, "did": ""}})
    out = workbench.prepare(root)
    assert list(out) == ["installed", "secrets", "schema", "seeded"]
    assert out["secrets"] == {"ok": True, "did": "a session secret of its own and a key for its sensitive columns"}
    assert sensitive_key(root) and "change-me" not in (root / ".env.local").read_text()
    assert workbench.prepare(root)["secrets"]["did"] == "", "and left alone after"
    assert workbench.PRECONDITIONS == ("installed", "secrets", "schema", "seeded", "server", "login")


def test_a_record_told_apart_by_name_is_told_apart_by_its_slug_too(monkeypatch):
    from services.expects import runner
    ent = {"id": "ENTITY-003", "name": "Category", "fields": [
        {"name": "name", "type": "string"}, {"name": "slug", "type": "string", "unique": True},
        {"name": "code", "type": "string"}, {"name": "description", "type": "string"}]}
    trial = runner.Trial.__new__(runner.Trial)
    trial.app = object()
    trial.stamp = "exp008"
    trial.log = []
    monkeypatch.setattr("services.blueprint.page_review._query", lambda app, q: [(1,)])
    values = trial._distinct_name(ent, "categories", {"name": "Electronics", "slug": "electronics", "code": "EL",
                                                     "description": "Phones and more", "isActive": True}, "cat")
    assert values["name"] == "Electronics EXP008"
    assert values["slug"] == "electronics-exp008" and values["code"] == "EL-exp008"
    assert values["description"] == "Phones and more" and values["isActive"] is True
    assert trial.log[-1].endswith("(and its slug, code with it)")
    monkeypatch.setattr("services.blueprint.page_review._query", lambda app, q: [])
    assert trial._distinct_name(ent, "categories", {"name": "Toys", "slug": "toys"}, "cat")["slug"] == "toys"


def test_an_unattended_turn_out_of_steps_lets_its_tries_speak(monkeypatch):
    from services.smith4 import turn as T
    from services.smith.loop import Observation
    failing = "EXP-008 does not hold — \"An active category appears in the Categories list a buyer browses.\"\n  - Buyer does not see 'Electronics EXP008' on /categories"
    observations = [
        Observation(tool="read_page_code", status="read", said="/categories reads active categories"),
        Observation(tool="try_expectation", status="read", said=failing),
        Observation(tool="open_page", status="read", said="/categories as Buyer: seven categories shown"),
    ]
    asked: list = []

    def choose(*a, **k):
        asked.append(1)
        return {"tool": "answer", "args": {"text": "The categories screen is already working correctly."}}
    ctx = SimpleNamespace(unattended=True, ask="fix EXP-008", project_id="p", out="/tmp/nowhere")
    out = T._out_of_steps(ctx, choose, observations, [], touched=[], out_of_time=False, max_steps=26)
    assert out.status == "no_op"
    assert out.said.startswith("What I tried, and what it showed — it still does not hold:\n- EXP-008 does not hold")
    assert "already working" not in out.said and asked == [], "the model is not asked for a verdict over its own try"
    ctx.unattended = False
    out = T._out_of_steps(ctx, choose, observations, [], touched=[], out_of_time=False, max_steps=26)
    assert "already working" in out.said, "a person's turn still hears Smith's reading of it"


def test_a_change_before_any_build_is_not_already_in_the_application(tmp_path):
    """ecom v3 (forge-v3, 2026-10-10): after the requirements were written,
    `build` answered "That change is already in the application — nothing
    needs rebuilding. Launch the preview" — before anything existed to launch."""
    from services.blueprint.service import BlueprintService
    from services.smith4.verbs import Ctx, rebuild
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    svc.save()
    ctx = Ctx(output_dir=str(tmp_path), project_id="p1", message="build", ask="build")
    ctx.applied = True
    out = rebuild(ctx, {})
    assert "nothing needs rebuilding" not in out.said and "Approve and build" in out.said
    svc.doc["runtime"] = {"build": {"status": "passed"}}
    svc.save()
    out = rebuild(ctx, {})
    assert out.status == "resolved" and "nothing needs rebuilding" in out.said


def test_a_failed_opening_node_runs_once_more_before_anyone_is_asked(tmp_path, monkeypatch):
    """ecom v3: `decisions` was refused twice for its shape and the person was
    told to press Build again."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_the_engineer_builds_feature_by_feature import _project
    from services.engineer.build import build
    _project(tmp_path)
    plans: list = []
    said: list[str] = []

    def run(svc, executor, *, plan, scope=None, **kw):
        plans.append(list(plan))
        if "decisions" in plan and len(plans) == 1:
            return SimpleNamespace(failed=["decisions"], paused_because="",
                                   failed_because={"decisions": "BlueprintInvalid: policies/decisions/0: 'about' is a required property"})
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda s, od, only=None, **kw: {"statements": len(only or []), "passed": len(only or []), "failing": [],
                                             "untried": [], "fixed": [], "results": [{"id": i, "verdict": "passed"} for i in only or []]}
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=lambda *a: {},
                emit=lambda k, d: said.append(d.get("text", "")), plan=["decisions", "install", "page_code", "assemble"])
    assert plans[1] == ["decisions"], "the failed node runs once more, alone"
    assert not out["stopped"] and any("decisions did not finish — trying once more" in t for t in said)
    assert not any("Build again" in t for t in said)

    plans.clear(); said.clear()
    run2 = lambda svc, executor, *, plan, scope=None, **kw: (plans.append(list(plan)) or SimpleNamespace(
        failed=["decisions"], paused_because="", failed_because={"decisions": "BlueprintInvalid: still wrong"}))
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run2, prove=prove, fix=lambda *a: {},
                emit=lambda k, d: said.append(d.get("text", "")), plan=["decisions", "install", "page_code", "assemble"])
    assert out["stopped"].startswith("the application could not be defined: decisions: BlueprintInvalid: still wrong")
    assert len(plans) == 2 and any("I could not finish defining the application" in t for t in said)
    assert not any("Build again" in t for t in said)
