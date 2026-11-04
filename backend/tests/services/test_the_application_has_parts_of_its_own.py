"""Every page used to be designed alone, so no two agreed except by luck.

Measured 2026-11-04 against a hand-designed application (Criterion CARES, the
one Forge app a person redesigned by hand): its coherence comes from a kit of
34 exports that 14 of its 22 pages import — one page head, one panel, one row,
one status pill — plus formatters reached for as often as the components
(`money` on 8 pages, `statusWord` 6, `dueWords` 5). Two applications built by
Forge the same day (Stay, Claimsdesk) authored *zero* shared components between
them; `src/components/shared/` held three scaffold files nothing imports.

So `component_kit` writes the product's own parts once, between the direction
and the pages, and every page composes from them.

The kit may name this product's colours and a page may not — a page held to the
semantic tokens can only produce a tasteful default, and a page free to name
colours produces thirty palettes. The kit's are enumerated in advance in
`componentKit.palette` and reached as `var(--kit-*)`, the same bargain the
drawn-page path makes (`ui_engineer._drawn_findings`).
"""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import component_kit
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.orchestrator import DAG, levels, run, write_overlaps
from services.blueprint.service import BlueprintService

PANEL = '''"use client";
import * as React from "react";
export function Panel({ title, children }: { title?: string; children?: React.ReactNode }) {
  return (
    <section className="rounded-[22px] border border-[var(--kit-line)] bg-[var(--kit-surface)] p-7">
      {title ? <h2 className="text-h2 font-heading">{title}</h2> : null}
      {children}
    </section>
  );
}
'''

KIT = {
    "rationale": "A procedural desk tool: hairline panels, no lift, tabular rows.",
    "palette": {"line": "#D7E4E1", "surface": "#FFFFFF", "wash": "#F2F7F6"},
    "parts": [
        {"file": "Panel.tsx", "purpose": "the container most of a page is made of",
         "exports": ["Panel"], "code": PANEL},
        {"file": "format.ts", "purpose": "this product's words and numbers",
         "exports": ["money", "statusWord"],
         "code": "export const money = (n: number) => `£${n.toFixed(2)}`;\n"
                 "export const statusWord = (s: string) => s.replace(/([A-Z])/g, ' $1');\n"},
    ],
}


def _doc(kit=None):
    return {"application": {"id": "a1", "name": "Claimsdesk"},
            "designSystem": {"colors": {"primary": "#0F5C5C"}, "register": "utility"},
            "navigation": {}, "pages": [{"id": "PAGE-001", "route": "/queue"}],
            **({"componentKit": kit} if kit is not None else {})}


# --- it is a node of the build, in the right place --------------------------

def test_the_kit_is_written_before_any_page_and_owned_by_one_node():
    assert write_overlaps(DAG) == []
    order = [k for lvl in levels() for k in lvl]
    assert order.index("ui_direction") < order.index("component_kit")
    assert order.index("component_kit") < order.index("page_code")
    assert "component_kit" in DAG["page_code"].depends_on, (
        "a page importing a part the kit has not written yet cannot compile")
    assert DAG["component_kit"].optional, "a kit that fails must never cost the app"


def test_the_kit_lands_in_the_blueprint_and_on_disk(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a1", name="Claimsdesk",
                                  domain="logistics")
    svc.doc["application"]["id"] = "a1"
    svc.save()

    def answer(spec):
        component_kit.project_component_kit({**svc.doc, "componentKit": KIT},
                                            Path(svc.output_dir) / "app")
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=[
            ArtifactProposal(section="componentKit", natural_key="componentKit", body=KIT)])

    report = run(svc, answer, plan=["component_kit"], app_root=str(tmp_path / "app"), commit=True)

    assert report.completed == ["component_kit"]
    stored = json.loads(svc.current_path.read_text())["componentKit"]
    assert [p["file"] for p in stored["parts"]] == ["Panel.tsx", "format.ts"]
    assert stored["palette"]["line"] == "#D7E4E1"
    kit_dir = tmp_path / "app" / component_kit.KIT_DIR
    assert (kit_dir / "Panel.tsx").exists() and (kit_dir / "palette.ts").exists()


# --- on disk ----------------------------------------------------------------

def test_the_palette_reaches_the_code_as_one_source(tmp_path):
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    module = (tmp_path / component_kit.KIT_DIR / "palette.ts").read_text("utf-8")
    assert 'line: "#D7E4E1"' in module and "export const C" in module
    assert component_kit.palette_vars(_doc(KIT)) == [
        "  --kit-line: #D7E4E1;", "  --kit-surface: #FFFFFF;", "  --kit-wash: #F2F7F6;"]


def test_the_palette_is_projected_beside_the_design_tokens(tmp_path):
    """A part writes `bg-[var(--kit-wash)]`; the var has to exist."""
    from services.blueprint.projection import project_design_tokens
    project_design_tokens(_doc(KIT), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text("utf-8")
    assert "--kit-wash: #F2F7F6;" in css


def test_a_part_the_kit_no_longer_declares_goes(tmp_path):
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    kit_dir = tmp_path / component_kit.KIT_DIR
    assert (kit_dir / "format.ts").exists()

    thinner = {**KIT, "parts": [KIT["parts"][0]]}
    component_kit.project_component_kit(_doc(thinner), tmp_path)
    assert not (kit_dir / "format.ts").exists(), "a page could still import yesterday's"
    assert (kit_dir / "Panel.tsx").exists()


def test_a_file_that_is_not_ours_is_left_alone(tmp_path):
    kit_dir = tmp_path / component_kit.KIT_DIR
    kit_dir.mkdir(parents=True)
    (kit_dir / "ByHand.tsx").write_text("export const ByHand = () => null;\n", "utf-8")
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    assert (kit_dir / "ByHand.tsx").exists(), "only files carrying the marker are ours to delete"


def test_projecting_twice_changes_nothing(tmp_path):
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    before = {f.name: (f.read_text("utf-8"), f.stat().st_mtime_ns)
              for f in (tmp_path / component_kit.KIT_DIR).iterdir()}
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    after = {f.name: (f.read_text("utf-8"), f.stat().st_mtime_ns)
             for f in (tmp_path / component_kit.KIT_DIR).iterdir()}
    assert before == after


def test_an_application_with_no_kit_gets_no_directory(tmp_path):
    assert component_kit.project_component_kit(_doc(), tmp_path) == []
    assert not (tmp_path / component_kit.KIT_DIR).exists()


def test_assembly_does_not_touch_the_kit(tmp_path, monkeypatch):
    """`copy_scaffold` overwrites template paths; the kit is not one, and a
    sweep that took it would break every page that imports it."""
    from services.blueprint import assembly
    template = tmp_path / "template"
    (template / "src").mkdir(parents=True)
    (template / "src" / "untouched.ts").write_text("// scaffold\n", "utf-8")
    out = tmp_path / "app"
    component_kit.project_component_kit(_doc(KIT), out)
    monkeypatch.setattr(assembly, "_template_dirs", lambda: [template])
    assembly.copy_scaffold(out, project_short_id="t1")
    assert (out / component_kit.KIT_DIR / "Panel.tsx").read_text("utf-8").endswith("}\n")


def test_nothing_the_kit_writes_looks_like_an_unfilled_placeholder(tmp_path):
    """`assembly.scaffold_tokens` scans the whole app `src/` and
    `refuse_unfilled_scaffold` fails the BUILD on a hit — comments included."""
    from services.blueprint.assembly import unfilled_scaffold_tokens
    component_kit.project_component_kit(_doc(KIT), tmp_path)
    assert list(unfilled_scaffold_tokens(tmp_path)) == []


# --- what the kit is held to ------------------------------------------------

def _finding(code, doc=None):
    return component_kit.findings(doc or _doc(KIT),
                                  [{"file": "X.tsx", "code": code}])


def test_a_hex_of_its_own_is_refused_but_still_draws():
    assert any("#efe6f8" in f for f in _finding('<p className="bg-[#efe6f8]" />'))
    assert _finding('<p className="bg-[var(--kit-wash)]" />') == []


def test_a_colour_the_palette_does_not_declare_costs_the_part():
    """The severities were the wrong way round. A raw hex RENDERS — it is only
    unthemeable, so it is a style finding and never costs a part. A var the
    palette does not declare makes the whole property invalid at computed time,
    the rule is dropped, and a label that should be red simply is not. The kit
    shipped `--kit-paid` and `--kit-wash` undeclared and they were kept
    (Claimsdesk, 2026-11-04)."""
    doc, part = _doc(KIT), [{"file": "X.tsx", "code": '<p className="bg-[var(--kit-plum)]" />'}]
    assert any("--kit-plum" in f for f in component_kit.undeclared_colours(doc, part))
    assert component_kit.findings(doc, part) == [], "not a style finding any more"
    # one it does declare is fine
    assert component_kit.undeclared_colours(
        doc, [{"file": "X.tsx", "code": '<p className="bg-[var(--kit-wash)]" />'}]) == []


def test_the_part_whose_colour_does_not_resolve_is_dropped(monkeypatch, tmp_path):
    ghost = {"file": "Ghost.tsx", "purpose": "names a colour that is not there",
             "exports": ["Ghost"], "code": '<p className="bg-[var(--kit-plum)]" />'}
    body, _ = _compose(monkeypatch, tmp_path, {**KIT, "parts": [*KIT["parts"], ghost]})
    assert [p["file"] for p in body["parts"]] == ["Panel.tsx", "format.ts"]


def test_a_scaffold_placeholder_is_refused_before_it_fails_the_build():
    assert any("__APP_NAME__" in f for f in _finding("const n = `__APP_NAME__`;"))
    assert any("{{app_name}}" in f for f in _finding("// {{app_name}} goes here"))


def test_a_part_may_not_read_data():
    assert any("reads data" in f for f in _finding('import { list } from "@/sdk/server";'))
    assert any("reads data" in f for f in _finding("await fetch('/api/x')"))


def test_a_part_that_uses_a_hook_says_so():
    assert any("use client" in f for f in _finding("const [a] = useState(1);"))
    assert _finding('"use client";\nconst [a] = useState(1);') == []


def test_the_shipped_kit_passes_its_own_rules():
    assert component_kit.findings(_doc(KIT), KIT["parts"]) == []


# --- and the page writer is handed it ---------------------------------------

def test_the_page_writer_is_given_the_kits_vocabulary():
    from services.blueprint.ui_engineer import system_prompt
    prompt = system_prompt(_doc(KIT))
    assert 'from "@/components/app/Panel"' in prompt
    assert "Panel" in prompt and "money" in prompt
    assert "the container most of a page is made of" in prompt
    assert "@/components/app/*" in prompt, "the writer believes any other import fails to compile"


def test_an_application_with_no_kit_is_told_nothing_about_one():
    from services.blueprint.ui_engineer import system_prompt
    assert component_kit.kit_vocabulary(_doc()) == ""
    # The import whitelist names the path either way ("when it has any"); what
    # must not appear is a vocabulary of parts that do not exist.
    assert 'from "@/components/app/' not in system_prompt(_doc())
    assert "compose from these first" not in system_prompt(_doc())


def test_the_kit_exports_are_read_off_the_code_when_none_are_declared():
    doc = _doc({**KIT, "parts": [{"file": "Row.tsx", "code": "export function Row() { return null; }"}]})
    assert component_kit.exports_of(doc) == {"Row": ["Row"]}


# --- and the engineer is asked for the right things -------------------------

def test_the_kit_engineer_is_asked_for_parts_and_for_words():
    system, user = component_kit.kit_prompts(_doc())
    assert "may name this product's colours and a page may not" in system.lower()
    assert "var(--kit-" in system
    for asked in ("the page head", "the status chip", "the empty state"):
        assert asked in user, asked
    assert "formatters" in user, "the words matter as much as the shapes"
    assert "never loads data" in user


def test_the_engineer_is_told_which_decisions_are_still_its_own():
    """The first kits honoured the token scale and stopped there: Claimsdesk's
    Panel was `rounded-md border border-border bg-muted/40 p-3`, every value
    stock, no decision made — while its StatusChip, where the job was obviously
    to design something, built six tones over the palette with `color-mix`
    (2026-11-04). The instruction offered its own values as an alternative to
    the scale and the scale always won, so it now names the dimensions the
    design system leaves unmade and says a stock surface is a choice too."""
    system, _ = component_kit.kit_prompts(_doc())
    assert "is not a neutral choice" in system
    for dimension in ("inner padding", "its edge", "its ground", "interactive"):
        assert dimension in system, dimension
    # …and the register decides where those go, so a dense tool is not pushed
    # toward ornament it should not have.
    assert "A dense console earns its character from exact values" in system


def test_the_engineer_is_told_tailwinds_spacing_ladder_is_not_the_designs():
    """First attempt at the instruction above moved STRUCTURE and not VALUES:
    the kit grew variants and a stated edge language, and every spacing value
    was still `p-3`/`p-4`/`gap-2` (2026-11-04, same Blueprint, prompt the only
    difference). The design states `--space-*`, exposed as `p-card`,
    `gap-section` and `p-row` — and nothing had ever referenced them."""
    system, _ = component_kit.kit_prompts(_doc())
    assert "Tailwind's ladder, not this product's" in system
    for named in ("p-card", "gap-section", "p-row"):
        assert named in system, named


def test_the_kit_is_asked_to_agree_with_itself():
    system, user = component_kit.kit_prompts(_doc())
    assert "One corner family, one padding rhythm" in system
    assert "settle the decisions the whole kit shares" in user
    assert "names the decisions every part shares" in user, (
        "the rationale is where they are written down for the next part")


def test_the_kit_implements_the_rhythm_the_director_chose():
    """RHYTHM_OPTIONS are recipes addressed to whoever writes the markup; once
    a kit exists, that is the kit."""
    doc = _doc()
    doc["composition"] = {"rhythm": {"header": "band", "lead": "gradient-band",
                                     "lists": "cards", "figures": "inline", "sections": "open"}}
    _, user = component_kit.kit_prompts(doc)
    assert "lists: `cards`" in user and "header: `band`" in user


def test_the_kit_engineer_may_write_the_kit_and_nothing_else():
    from services.blueprint.agent_contract import AGENT_REGISTRY
    assert AGENT_REGISTRY["kit_engineer"].writes == {"componentKit"}
    assert DAG["component_kit"].agent == "kit_engineer"


# --- a kit that does not compile must not empty the application -------------

class _Client:
    """Replies in order; the last one repeats."""

    accepts_images = False
    max_tokens = 64000

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, *, system, user, schema, **kw):
        self.calls.append(user)
        return json.dumps(self.replies[min(len(self.calls), len(self.replies)) - 1])


BROKEN = {"file": "Broken.tsx", "purpose": "does not compile", "exports": ["Broken"],
          "code": "export const Broken = (p: {n: number}) => p.n.toUpperCase();\n"}


def _compose(monkeypatch, tmp_path, *replies, compile_errors=()):
    seen = iter(compile_errors) if compile_errors else None

    def fake_typecheck(app_root, timeout=180.0):
        if seen is None:
            return []
        return next(seen, [])

    monkeypatch.setattr(component_kit, "typecheck", fake_typecheck)
    client = _Client(*replies)
    body, _ = component_kit.compose_kit(_doc(), client, tmp_path, rounds=2)
    return body, client


def test_a_part_that_does_not_compile_is_handed_back_its_errors(monkeypatch, tmp_path):
    bad = {**KIT, "parts": [*KIT["parts"], BROKEN]}
    body, client = _compose(monkeypatch, tmp_path, bad, KIT,
                            compile_errors=[["Broken.tsx(1,52): error TS2339: no toUpperCase"], []])
    assert len(client.calls) == 2
    assert "Broken.tsx(1,52)" in client.calls[1], "the compiler's own words go back"
    assert [p["file"] for p in body["parts"]] == ["Panel.tsx", "format.ts"]


def test_the_part_that_will_not_compile_is_dropped_and_the_rest_kept(monkeypatch, tmp_path):
    """Every page imports the kit, and `settle_code_pages` deletes a page's code
    after it fails to compile twice — so one bad part shipped would empty the
    application. Six good parts beat seven with a casualty."""
    bad = {**KIT, "parts": [*KIT["parts"], BROKEN]}
    body, _ = _compose(monkeypatch, tmp_path, bad,
                       compile_errors=[["Broken.tsx(1,52): error TS2339: no toUpperCase"],
                                       ["Broken.tsx(1,52): error TS2339: no toUpperCase"],
                                       []])
    assert [p["file"] for p in body["parts"]] == ["Panel.tsx", "format.ts"]
    kit_dir = tmp_path / component_kit.KIT_DIR
    assert not (kit_dir / "Broken.tsx").exists(), "a page could still import it"
    assert (kit_dir / "Panel.tsx").exists()


def test_a_kit_that_cannot_be_cut_down_is_not_shipped_at_all(monkeypatch, tmp_path):
    """Cutting one part can break another that imported it. No kit is
    survivable — the pages are written in the token classes, as they were
    before this node existed."""
    bad = {**KIT, "parts": [*KIT["parts"], BROKEN]}
    body, _ = _compose(monkeypatch, tmp_path, bad,
                       compile_errors=[["Broken.tsx(1,1): error TS1"],
                                       ["Broken.tsx(1,1): error TS1"],
                                       ["Panel.tsx(3,1): error TS2 the rest broke too"]])
    assert body["parts"] == []
    assert not list((tmp_path / component_kit.KIT_DIR).glob("*.tsx"))
    assert (tmp_path / component_kit.KIT_DIR / "palette.ts").exists(), "the colours stand alone"


def test_an_error_no_part_owns_ships_no_kit(monkeypatch, tmp_path):
    body, _ = _compose(monkeypatch, tmp_path, KIT,
                       compile_errors=[["../../src/sdk/x.ts(1,1): error TS9"],
                                       ["../../src/sdk/x.ts(1,1): error TS9"]])
    assert body["parts"] == [], "we cannot cut precisely, so we do not cut"


def test_a_style_finding_never_costs_a_part(monkeypatch, tmp_path):
    """An unthemed chip is worth more than no chip, and the page it sits on
    still compiles — the same tier `_design_findings` sits in."""
    loud = {**KIT, "parts": [{**KIT["parts"][0],
                              "code": KIT["parts"][0]["code"].replace(
                                  "var(--kit-line)", "#D7E4E1")}]}
    body, _ = _compose(monkeypatch, tmp_path, loud)
    assert [p["file"] for p in body["parts"]] == ["Panel.tsx"]


def test_the_reply_schema_is_one_the_model_will_accept():
    """A structured reply may not carry a free-form object. `palette` was
    `{"additionalProperties": {"type": "string"}}` and the provider refused the
    request outright — "For 'object' type, 'additionalProperties: object' is not
    supported" — so the node 400'd on both attempts and wrote nothing
    (Claimsdesk, 2026-11-04). Faked clients cannot see this; the shape can."""
    def walk(node, path="schema"):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, (
                f"{path}: an object in a reply schema must close itself")
        for key in ("properties", "items", "$defs"):
            child = node.get(key)
            if isinstance(child, dict) and key == "properties":
                for k, v in child.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(child, dict):
                walk(child, f"{path}.{key}")
    walk(component_kit.KIT_SCHEMA)


def test_the_palette_comes_back_as_named_entries():
    assert component_kit._palette_map(
        [{"name": "wash", "value": "#F2F7F6"}, {"name": "ink", "value": "#15241F"}]
    ) == {"wash": "#F2F7F6", "ink": "#15241F"}
    # a map still lands, so a hand-written body is not refused
    assert component_kit._palette_map({"wash": "#F2F7F6"}) == {"wash": "#F2F7F6"}
    assert component_kit._palette_map(None) == {}


def test_the_engineer_is_asked_for_the_shape_the_schema_wants():
    _, user = component_kit.kit_prompts(_doc())
    assert "{name, value}" in user


def test_an_escape_in_jsx_text_is_refused_in_a_part_too():
    """JSX text is not a JavaScript string, so `\\u00b7` reaches the screen as
    six characters. The page writer has been held to this since SnapIT
    (2026-10-01); the kit was outside the rule and Stay's lead card shipped
    "Nov 1 – Nov 1 \\u00b7 0 nights" (2026-11-04)."""
    assert any("shown" in f for f in _finding('<span>{a} \\u00b7 {b}</span>'))
    assert any("shown" in f for f in _finding('<img alt="a \\u2014 b" />'))
    # inside a JS expression it is a real string, and fine
    assert _finding('<p>{facts.join(" \\u00b7 ")}</p>') == []
    assert _finding("const dash = `${a} \\u2013 ${b}`;") == []
