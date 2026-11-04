"""Every page is looked at as it is written — and the writer is free of the kit.

The compiler accepted pages nobody had seen: the only look (`page_review`)
came after the whole app was assembled, as an opt-in verb. Now a page that
compiles is rendered with sample data, judged on its desk and phone
screenshots, and sent back once with the review as its brief; the version
the reviewer ranked higher is what the page keeps, and a machine that
cannot render accepts the page as the compiler did. The writer's rules no
longer confine it to the shadcn kit — the kit was the declarative engine's
vocabulary; a React page is markup — but the components that carry the
wiring stay mandatory. And taste has inputs: the user's reference images
reach the design director and the reviewer, and the brief's palette
question invites one.
"""
import json
from pathlib import Path

import pytest

from services.blueprint import page_look, ui_engineer
from services.blueprint.references import READ_FOR
from services.blueprint.ui_engineer import CompileError, TECH_RULES, compose_direction, compose_page, system_prompt

ROOT = Path(__file__).resolve().parents[2]
GOOD_VIEW = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
BETTER_VIEW = '"use client";\nexport default function View() { return <section className="p-6">Better</section>; }\n'
GOOD_LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'


def _doc():
    return {"application": {"id": "t", "name": "Desk", "description": "Cases."},
            "data": {"entities": [{"id": "ENTITY-001", "name": "Case", "fields": [{"name": "title", "type": "string"}]}]},
            "pages": [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "Every case.",
                       "data": {"primaryEntity": "ENTITY-001"}}],
            "workflows": [], "composition": {"vision": "Calm.", "conventions": []}}


class _Writer:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, *, system, user, schema, **_):
        self.calls.append(user)
        return json.dumps(self.replies.pop(0))


class _Critic:
    accepts_images = True

    def __init__(self, verdicts):
        self.verdicts, self.seen = list(verdicts), []

    def __call__(self, *, system, user, schema, images=()):
        self.seen.append((user, list(images)))
        return json.dumps(self.verdicts.pop(0))


def _looks(monkeypatch, verdicts):
    """A render that needs no browser: the judge sees fake screenshots."""
    critic = _Critic(verdicts)
    monkeypatch.setattr(page_look, "render", lambda *a, **k: {"shots": {"desktop": "d.png", "mobile": "m.png"}, "errors": []})
    return critic


@pytest.fixture(autouse=True)
def _no_compiler(monkeypatch):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ui_engineer, "_page_plan", lambda *a, **k: None)


PASS = {"score": 9, "verdict": "pass", "strengths": ["clear"], "issues": []}
REVISE = {"score": 5, "verdict": "revise", "strengths": ["the table"],
          "issues": [{"severity": "high", "where": "header", "problem": "no sort affordance", "fix": "add a glyph"}]}


def test_a_page_the_reviewer_sends_back_is_rewritten_from_the_review(monkeypatch, tmp_path):
    critic = _looks(monkeypatch, [REVISE, PASS])
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW},
                      {"rationale": "", "load": GOOD_LOAD, "view": BETTER_VIEW}])
    body, spent = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    assert body["view"] == BETTER_VIEW
    assert len(writer.calls) == 2 and len(critic.seen) == 2
    assert "scored it 5/10" in writer.calls[1] and "no sort affordance" in writer.calls[1]
    assert GOOD_VIEW.strip() in writer.calls[1], "the rewrite is shown the page it is improving"
    assert [s[2] for s in spent if len(s) == 3] == [], "a fake reply has no usage to record"


def test_the_reviewer_sees_both_screenshots_and_the_contract(monkeypatch, tmp_path):
    critic = _looks(monkeypatch, [PASS])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}]),
                 critic=critic)
    user, images = critic.seen[0]
    assert images == ["d.png", "m.png"] and "desktop (1280px wide)" in user and "mobile (390px wide)" in user
    assert '"route": "/cases"' in user and "sample data" in user


def test_a_rewrite_that_scores_lower_is_not_kept(monkeypatch, tmp_path):
    worse = dict(REVISE, score=4)
    critic = _looks(monkeypatch, [REVISE, worse])
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW},
                      {"rationale": "", "load": GOOD_LOAD, "view": BETTER_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    assert body["view"] == GOOD_VIEW, "the version the reviewer ranked higher"
    assert len(critic.seen) == 2, (
        "and it stops THERE — not because the budget ran out (that is 5 now) but "
        "because the rewrite scored lower, so another one buys nothing")


def test_a_rewrite_that_does_not_compile_keeps_the_judged_version(monkeypatch, tmp_path):
    critic = _looks(monkeypatch, [REVISE])
    seen = iter([[]] + [["view.tsx(1,1): error TS2304"]] * 12)
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: next(seen))
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}]
                     + [{"rationale": "", "load": GOOD_LOAD, "view": BETTER_VIEW}] * 12)
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    assert body["view"] == GOOD_VIEW


def test_a_machine_that_cannot_render_accepts_the_page_as_compiled(monkeypatch, tmp_path):
    def cannot(*a, **k):
        raise page_look.LookUnavailable("browser: no chromium")
    monkeypatch.setattr(page_look, "render", cannot)
    critic = _Critic([REVISE])
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    assert body["view"] == GOOD_VIEW and len(writer.calls) == 1 and critic.seen == []


def test_without_a_critic_nothing_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(page_look, "render", lambda *a, **k: pytest.fail("no look without a critic"))
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer)
    assert body["view"] == GOOD_VIEW
    bad = 'export default function View() { return <div style={{ color: "#ff0000" }} />; }'
    with pytest.raises(CompileError):
        compose_page(_doc(), _doc()["pages"][0], tmp_path,
                     _Writer([{"rationale": "", "load": GOOD_LOAD, "view": bad}] * ui_engineer.COMPILE_ROUNDS))


def test_what_the_browser_proved_broken_fails_the_page_whatever_it_scores():
    critic = _Critic([dict(PASS, score=10)])
    look = {"shots": {"desktop": "d.png"}, "errors": ["view.tsx: Cannot read properties of null"]}
    verdict, _ = page_look.judge(_doc(), _doc()["pages"][0], look, critic)
    assert verdict["verdict"] == "revise" and verdict["broken"] == look["errors"]
    brief = page_look.look_brief(verdict)
    assert "BROKEN" in brief and "Cannot read properties of null" in brief
    assert page_look.rank(verdict) < page_look.rank(dict(PASS, broken=[]))


def test_the_document_is_the_canvas_frame_and_catches_the_pages_own_errors():
    html = page_look.frame_html("body{}", "var v=1;", "var p=2;")
    assert '<div id="root"></div>' in html and "forge-editor:error" in html
    assert html.index("var v=1;") < html.index("var p=2;"), "the shared script loads before the page"


# --- the writer is free of the kit --------------------------------------------

def test_the_writer_is_not_confined_to_the_kit():
    assert "Imports allowed, and only these" not in TECH_RULES
    assert "THE PAGE IS YOURS TO BUILD" in TECH_RULES and "clsx" in TECH_RULES
    for must in ("<SignInForm />", "<WorkflowForm />", "<WorkflowButton />", "<WidgetView />", "href(pages.x)"):
        assert must in TECH_RULES, must
    prompt = system_prompt(_doc())
    assert "there if one fits, never required" in prompt
    assert "Do not use\nany other library component" not in prompt
    assert "focus-visible:ring-2" in ui_engineer.DESIGN_PRINCIPLES


# --- taste has inputs -----------------------------------------------------------

def test_the_director_and_the_reviewer_read_the_users_references():
    assert "ui_direction" in READ_FOR and "page_look" in READ_FOR
    assert "FEEL" in READ_FOR["ui_direction"] and "the bar" in READ_FOR["page_look"]


def test_the_director_is_shown_the_references_when_it_can_see():
    class Sees:
        accepts_images = True

        def __init__(self):
            self.images = None

        def __call__(self, *, system, user, schema, images=()):
            self.images = list(images)
            assert READ_FOR["ui_direction"][:40] in user
            return json.dumps({"vision": "v", "conventions": [], "rhythm": {}})
    client = Sees()
    compose_direction(_doc(), client, references=[Path("/tmp/ref.png")])
    assert client.images == ["/tmp/ref.png"]
    blind = _Writer([{"vision": "v", "conventions": []}])
    compose_direction(_doc(), blind, references=[Path("/tmp/ref.png")])
    assert "ref.png" not in blind.calls[0], "a client that cannot see is not told about a picture"


def test_the_reviewer_is_shown_the_references_as_the_bar(tmp_path):
    critic = _Critic([PASS])
    look = {"shots": {"desktop": "d.png"}, "errors": []}
    page_look.judge(_doc(), _doc()["pages"][0], look, critic, references=[tmp_path / "bar.png"])
    user, images = critic.seen[0]
    assert images == ["d.png", str(tmp_path / "bar.png")] and "the standard they want" in user


def test_the_palette_question_invites_a_screenshot():
    src = (ROOT / "services/smith/clarify_brief.py").read_text()
    assert "attach a screenshot of a product whose" in src


def test_the_executor_hands_the_writer_a_critic_and_records_its_cost():
    src = (ROOT / "services/blueprint/executors.py").read_text()
    assert 'model.for_task("page_look", "page_reviewer")' in src
    assert 'for u, elapsed, *who in spent' in src
    assert "compose_direction(doc, client, references=references.paths(svc.output_dir))" in src


def test_a_look_lays_down_what_the_bundle_needs_before_assembly(monkeypatch, tmp_path):
    """The vendored renderer imports feel-lite, which assembly copies AFTER
    every page is written; on UAT every look of a fresh build failed to
    bundle and every page shipped unseen (i3i950po, 2026-09-25)."""
    from services.blueprint import page_look
    from services.blueprint.assembly import LOOSE_LIBS
    app = tmp_path / "app"; (app / "src").mkdir(parents=True)
    seen = {}

    def fake_bundle(project, doc, page, view, load, **_):
        seen["laid"] = all((app / dst).is_dir() for dst in LOOSE_LIBS.values())
        raise __import__("services.react_editor.service", fromlist=["EditorError"]).EditorError(422, "jit-build", "stop here")
    monkeypatch.setattr("services.react_editor.jit.bundle_source", fake_bundle)
    projected = []
    monkeypatch.setattr("services.blueprint.projection.project_design_tokens", lambda doc, root: projected.append(root))
    with pytest.raises(page_look.LookUnavailable):
        page_look.render(_doc(), _doc()["pages"][0], app, GOOD_LOAD, GOOD_VIEW, tmp_path / "out")
    assert seen["laid"] is True, "feel-lite is in the tree before the bundle is asked for"
    assert projected == [app], "the design's tokens are projected before the bundle, not the scaffold's default theme"


def test_the_sample_person_owns_the_sample_rows():
    """A record shown only to its owner rendered "Not found" in the editor and
    in every look: the sample user was nobody's parent (rafm22pm, 2026-09-26)."""
    import json, subprocess
    shim = ROOT / "static/jit-samples.mjs"
    src = subprocess.run(["node", "-e", f"""
      import({json.dumps(str(shim))}).then(m => {{
        const ents = [{{name: "Parent", account: true, fields: [{{name: "id", type: "uuid"}}, {{name: "fullName", type: "string"}}, {{name: "email", type: "string"}}]}},
                      {{name: "Child", fields: [{{name: "id", type: "uuid"}}, {{name: "parentId", type: "uuid"}}]}}];
        const s = m.sampleServer(ents, ["parent"]);
        const child = m.sampleRow(ents[1], 0, ents);
        console.log(JSON.stringify({{server: s, childParent: child.parentId}}));
      }})"""], capture_output=True, text=True, check=True).stdout
    out = json.loads(src)
    assert '"id":"sample-parent-1"' in out["server"].replace(" ", ""), "currentUser() is the account's first sample row"
    assert out["childParent"] == "sample-parent-1", "and the first child points at it"


def test_a_look_lays_down_feel_lite_where_there_is_no_frontend_checkout(monkeypatch, tmp_path):
    """In the backend image the loose libraries' checkout source does not
    exist and `copy_loose_libs` copies nothing; the look must take the
    runtime template the app itself ships with (UAT, SnapIT and RK_Test)."""
    from services.blueprint import assembly, page_look
    app = tmp_path / "app"; (app / "src").mkdir(parents=True)
    monkeypatch.setattr(assembly, "LOOSE_LIBS", {"no/such/checkout/feel-lite": "src/lib/feel-lite"})
    seen = {}

    def fake_bundle(project, doc, page, view, load, **_):
        seen["laid"] = (app / "src/lib/feel-lite/index.ts").is_file()
        raise __import__("services.react_editor.service", fromlist=["EditorError"]).EditorError(422, "jit-build", "stop")
    monkeypatch.setattr("services.react_editor.jit.bundle_source", fake_bundle)
    monkeypatch.setattr("services.blueprint.projection.project_design_tokens", lambda doc, root: None)
    with pytest.raises(page_look.LookUnavailable):
        page_look.render(_doc(), _doc()["pages"][0], app, GOOD_LOAD, GOOD_VIEW, tmp_path / "out")
    assert seen["laid"] is True, "feel-lite came from the runtime templates"


# --- a page is looked at while it is getting better -------------------------
#
# The budget was a flat two — one look at the compiled page, one at its
# rewrite — and the page shipped whatever it had. Measured over two whole
# builds (Claimsdesk and Stay, 2026-11-04): FIFTEEN OF EIGHTEEN PAGES WERE
# STILL `revise` when their looks ran out, at a median of 5/10 and 6.5/10,
# and both builds reported no failures. Every one stopped because it ran out
# of looks, never because it was good enough. Of the eighteen, seven were
# still climbing (1→5, 4→7, 4→5…) and three had gone BACKWARDS (6→5, 7→5,
# 4→2), because a look rewrites the page whole and a rewrite loses what was
# already right.

def _trail(monkeypatch, tmp_path, scores):
    """Drive the loop with a given score trail; return how many looks it took."""
    verdicts = [dict(REVISE, score=s) if s < 8 else dict(PASS, score=s) for s in scores]
    critic = _looks(monkeypatch, verdicts)
    writer = _Writer([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}] * (len(scores) + 2))
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    return len(critic.seen), body


def test_a_page_that_keeps_improving_keeps_being_looked_at(monkeypatch, tmp_path):
    """Claimsdesk's Decision Panel went 1 → 5 and shipped at 5, with the
    budget spent rather than the page finished."""
    seen, _ = _trail(monkeypatch, tmp_path, [1, 3, 5, 6, 7])
    assert seen == 5, seen


def test_a_page_a_rewrite_made_worse_stops_there(monkeypatch, tmp_path):
    """Supervisor 6→5, Escalations 7→5, Users 4→2. Spending the rest of the
    budget on the same reading of the same page buys nothing."""
    seen, _ = _trail(monkeypatch, tmp_path, [6, 5, 9])
    assert seen == 2, seen


def test_a_page_that_stalls_stops_there(monkeypatch, tmp_path):
    """Stay's My Stay went 6 → 6: the writer has shown it cannot get past
    this reading of its own page."""
    seen, _ = _trail(monkeypatch, tmp_path, [6, 6, 9])
    assert seen == 2, seen


def test_a_page_good_enough_is_not_rewritten(monkeypatch, tmp_path):
    seen, _ = _trail(monkeypatch, tmp_path, [8, 9])
    assert seen == 1, seen


def test_the_budget_is_a_ceiling_a_climbing_page_cannot_pass(monkeypatch, tmp_path):
    """A page that improves by a point every time still has to stop."""
    seen, _ = _trail(monkeypatch, tmp_path, [1, 2, 3, 4, 5, 6, 7])
    assert seen == page_look.LOOKS, seen


def test_the_rounds_budget_grows_with_the_looks():
    """`rounds = COMPILE_ROUNDS + looks - 1` gates the loop too, so raising
    the looks alone would have changed nothing — and a page that took every
    compile round used to have no round left to act on its review at all
    (Claimsdesk's Claims Queue was looked at once, scored 5, and shipped)."""
    from services.blueprint.ui_engineer import COMPILE_ROUNDS
    assert page_look.LOOKS > 2
    assert COMPILE_ROUNDS + page_look.LOOKS - 1 >= 7


def test_what_the_rule_would_have_done_to_the_builds_that_prompted_it():
    """The real trails, replayed. The eight that stop are exactly the ones a
    further look could not have helped."""
    kept_going = {"1,5": True, "4,7": True, "4,5": True, "6,7": True, "5": True,
                  "6,5": False, "7,5": False, "4,2": False, "6,6": False,
                  "7,7": False, "5,8": False, "8": False}
    for trail, expected in kept_going.items():
        scores, best = [int(x) for x in trail.split(",")], None
        for s in scores:
            keep = page_look.worth_another_look({"score": s}, best)
            best = s if best is None else max(best, s)
        assert keep is expected, (trail, keep)


def test_a_page_that_ships_below_the_bar_says_so(monkeypatch, tmp_path, caplog):
    """Both builds reported no failures while their own reviewer had rejected
    most of their pages. The verdicts were in the ledger and nothing read
    them back."""
    import logging
    with caplog.at_level(logging.WARNING, logger="services.blueprint.ui_engineer"):
        _trail(monkeypatch, tmp_path, [5, 4])
    said = [r.getMessage() for r in caplog.records]
    assert any("ships at 4/10, still `revise` after 2 look(s)" in m for m in said), said
    assert any("no sort affordance" in m for m in said), said
