"""The native engineer: one page as a React Native screen, held to the compiler.

It writes the page the web already has, for the phone, against the native SDK
and kit; every reply is checked by what a web page is checked by — the page
rules (every workflow the page launches has a control, every flow move leads
somewhere, no change is faked in state) — plus the rules of the platform (no
web imports or elements, no hard-coded colour), and then by the compiler
against the application's own generated types. What goes back to the writer is
the errors; what comes out compiles. A change that needs a workflow no one has
is the web's answer: `NeedsWorkflow`."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import native_engineer as ne
from services.blueprint.native_projection import native_root
from services.blueprint.ui_engineer import CompileError, NeedsWorkflow

DOC = {
    "application": {"name": "Field Crew"}, "product": {"locale": "en-GB"},
    "mobile": {"native": {"enabled": True}, "store": {"bundleId": "com.acme.fieldcrew"}},
    "designSystem": {"colors": {"primary": "hsl(243 75% 59%)"}, "visualPersonality": "Calm and practical."},
    "composition": {"vision": "Crew first, office second.", "conventions": [{"topic": "empty", "rule": "invite the first one"}]},
    "roles": [], "security": {},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Job", "fields": [
        {"name": "title", "type": "text"}, {"name": "price", "type": "money"}]}]},
    "workflows": [{"id": "WF-001", "name": "Close job", "launchedFrom": ["PAGE-001"],
                   "trigger": {"type": "manual"}, "inputs": [], "steps": []}],
    "pages": [{"id": "PAGE-001", "name": "Jobs", "route": "/", "access": "authenticated", "requirements": ["REQ-001"]}],
}
PAGE = DOC["pages"][0]

GOOD = '''import { Screen, ListView, ListItem, WorkflowButton } from "@/ui";
import { useList, workflows } from "@/sdk";
export default function JobsScreen() {
  const jobs = useList("Job");
  return (
    <Screen title="Jobs" loading={jobs.loading} error={jobs.error} onRetry={jobs.refetch}>
      <ListView list={jobs} renderItem={(j) => <ListItem title={j.title ?? ""} />} />
      <WorkflowButton workflow={workflows.closeJob} input={{}}>Close</WorkflowButton>
    </Screen>
  );
}
'''


def _reply(**body):
    return SimpleNamespace(text=json.dumps({"rationale": "r", "screen": GOOD, "needs": [], **body}), usage=None)


class Client:
    """A writer: a plain callable, so `_with` leaves it alone."""

    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    def __call__(self, *, system, user, schema):
        self.asked.append(user)
        return self.replies.pop(0)


def _compose(client, check=lambda screen: [], **kw):
    return ne.compose_screen(DOC, PAGE, Path("unused"), client, check=check, **kw)


# --- what the writer is told ------------------------------------------------

def test_the_prompt_carries_the_native_sdk_the_rules_and_this_applications_types():
    system = ne.system_prompt(DOC)
    assert "native engineer of Field Crew" in system and "Crew first, office second." in system
    assert "WorkflowForm" in system and "useList" in system, "the template's own API guide"
    assert "export default function Screen" in system
    assert "interface Job" in system and "closeJob" in system, "the application's generated types"
    assert "theme.colors.primary" in system


def test_the_guide_is_the_templates_own_readme():
    guide = ne.sdk_guide()
    assert guide.startswith("### What a screen imports") and "## Tests" not in guide
    assert "useWorkflow" in guide and "ListView" in guide


# --- the rules of the platform ----------------------------------------------

@pytest.mark.parametrize("code,needle", [
    ("export default function S() { return <div />; }", "HTML elements"),
    ('import Link from "next/link";\nexport default function S() { return null; }', "web module"),
    ('import { Plus } from "lucide-react";\nexport default function S() { return null; }', "web module"),
    ('export default function S() { return <View className="p-4" />; }', "className"),
    ('export default function S() { return <View style={{ color: "#fff" }} />; }', "hex colour"),
    ('export default function S() { fetch("/api/data/jobs"); return null; }', "fetch"),
    ("export function S() { return null; }", "default export"),
])
def test_a_screen_that_is_not_react_native_is_refused(code, needle):
    assert any(needle in e for e in ne._native_findings(code)), code


def test_a_clean_screen_has_no_platform_findings():
    assert ne._native_findings(GOOD) == []


# --- the page rules, as the web's ---------------------------------------------

def test_a_launched_workflow_with_no_control_is_refused():
    missing = GOOD.replace('<WorkflowButton workflow={workflows.closeJob} input={{}}>Close</WorkflowButton>', "")
    errors = ne._page_findings(DOC, PAGE, missing)
    assert any("Close job" in e and "Screen.tsx" in e for e in errors), errors
    assert ne._page_findings(DOC, PAGE, GOOD) == []


def test_a_change_faked_in_state_is_refused():
    faked = GOOD.replace("</Screen>", '<Button onPress={() => { setRows((r) => r.filter((x) => x.id !== id)); }} /></Screen>')
    assert any("workflow" in e for e in ne._page_findings(DOC, PAGE, faked))


# --- the loop ---------------------------------------------------------------

def test_a_screen_that_compiles_is_returned_with_its_page_and_requirements():
    body, spent = _compose(Client(_reply()))
    assert body["page"] == "PAGE-001" and body["screen"] == GOOD and body["parts"] == {}
    assert body["requirements"] == ["REQ-001"] and spent == []


def test_what_the_compiler_refuses_goes_back_to_the_writer_and_the_second_try_is_kept():
    bad, fixed = _reply(screen=GOOD.replace('"Jobs"', '"Jobs" bogus={1}')), _reply()
    client = Client(bad, fixed)
    calls = []

    def check(screen):
        calls.append(screen)
        return ["Screen.tsx(5,5): error TS2322: nope"] if "bogus" in screen else []

    body, _ = _compose(client, check=check)
    assert body["screen"] == GOOD and len(calls) == 2
    assert "TS2322: nope" in client.asked[1], "the second round is told what was wrong"
    assert "bogus" in client.asked[1], "…and shown the screen that was refused"


def test_a_screen_the_compiler_never_accepts_fails_the_page():
    client = Client(*[_reply() for _ in range(5)])
    with pytest.raises(CompileError, match="still does not compile"):
        _compose(client, check=lambda screen: ["Screen.tsx(1,1): error TS1: never"])
    assert len(client.asked) == 3


def test_a_reply_that_is_not_json_is_asked_again():
    client = Client(SimpleNamespace(text="not json", usage=None), _reply())
    body, _ = _compose(client)
    assert body["screen"] == GOOD and "not valid JSON" in client.asked[1]


def test_with_no_compiler_a_screen_is_accepted_on_its_page_rules():
    body, _ = _compose(Client(_reply()), check=lambda screen: None)
    assert body["screen"] == GOOD
    client = Client(_reply(screen="export default function S() { return <div />; }"), _reply())
    body, _ = _compose(client, check=lambda screen: None)
    assert body["screen"] == GOOD, "the page rules still hold without a compiler"


def test_a_change_that_needs_a_workflow_nobody_has_asks_for_one():
    client = Client(_reply(needs=["archive a job"]))
    with pytest.raises(NeedsWorkflow) as need:
        _compose(client, current={"screen": GOOD}, brief="add an archive button")
    assert need.value.needs == ["archive a job"]


# --- the compiler itself, when there is one ----------------------------------

SCRATCH = os.environ.get("FORGE_NATIVE_TOOLCHAIN", "")
needs_toolchain = pytest.mark.skipif(
    not (SCRATCH and (Path(SCRATCH) / "node_modules" / "typescript" / "bin" / "tsc").is_file() and shutil.which("node")),
    reason="set FORGE_NATIVE_TOOLCHAIN to a directory with the template's packages installed")


@needs_toolchain
def test_the_compiler_accepts_a_screen_written_against_the_applications_own_types(tmp_path):
    root = native_root(tmp_path)
    assert ne.typecheck(DOC, root, "PAGE-001", GOOD) == []


@needs_toolchain
def test_the_compiler_refuses_a_column_the_entity_does_not_have(tmp_path):
    root = native_root(tmp_path)
    errors = ne.typecheck(DOC, root, "PAGE-001", GOOD.replace("j.title", "j.titel"))
    assert errors and errors[0].startswith("Screen.tsx(") and "titel" in errors[0]
    errors = ne.typecheck(DOC, root, "PAGE-001", GOOD.replace('useList("Job")', 'useList("Nope")'))
    assert errors, "an entity the application does not have"
    errors = ne.typecheck(DOC, root, "PAGE-001", GOOD.replace("workflows.closeJob", "workflows.nothing"))
    assert errors, "a workflow the application does not have"


def test_with_no_toolchain_there_is_no_compiler_to_ask(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_NATIVE_TOOLCHAIN", str(tmp_path / "empty"))
    monkeypatch.setattr(ne.shutil, "which", lambda name, **kw: None)
    assert ne.ensure_toolchain() is None
