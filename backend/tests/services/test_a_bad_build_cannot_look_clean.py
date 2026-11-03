"""The four ways kkb5mzo3 produced a broken app that reported success.

2026-11-02, forge-v3. A build finished `completed: 18, failed: [], blocked: [],
skipped: []` while carrying a page set covering 2 of 18 modules, 15 unrepaired
findings, and no page code at all. Each test below is one of the reasons the
run could say that and be believed."""

from pathlib import Path

import pytest

from services.blueprint import observer as obs_mod
from services.blueprint.orchestrator import (
    NEEDS_TOOLCHAIN,
    toolchain_ready,
    with_toolchain,
)
from services.blueprint.verification import Finding


# -- 1. a node that compiles needs a compiler ------------------------------

def test_install_returns_to_the_plan_when_its_output_is_gone(tmp_path):
    """`install` produces no Blueprint section, so nothing else notices."""
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    assert not toolchain_ready(str(app))
    assert with_toolchain(["page_code"], str(app)) == ["install", "page_code"]
    assert with_toolchain(["native_code", "frontend"], str(app))[0] == "install"


def test_a_present_compiler_is_left_alone(tmp_path):
    app = tmp_path / "app"
    binx = app / "node_modules" / ".bin"
    binx.mkdir(parents=True)
    tsc = binx / "tsc"
    tsc.write_text("#!/bin/sh\n")
    tsc.chmod(0o755)
    assert toolchain_ready(str(app))
    assert with_toolchain(["page_code"], str(app)) == ["page_code"]


def test_only_the_nodes_that_compile_pull_it_in(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    assert with_toolchain(["requirements", "data_model"], str(app)) == ["requirements", "data_model"]
    assert "page_code" in NEEDS_TOOLCHAIN and "native_code" in NEEDS_TOOLCHAIN


def test_no_app_root_means_no_claim():
    """A caller that projects nowhere has no tree to inspect or install into.

    Injecting `install` there made it unrunnable and skipped every dependent
    — it broke `test_pages_wait_for_credit_rather_than_ship_on_the_floor`,
    which runs the scheduler with app_root=None."""
    assert with_toolchain(["page_code"], None) == ["page_code"]
    assert with_toolchain(["page_code"], "") == ["page_code"]


def test_install_is_not_added_twice(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    assert with_toolchain(["install", "page_code"], str(app)) == ["install", "page_code"]


# -- 2. a finding that names no artifact is still recorded ------------------

class _Svc:
    """Enough BlueprintService for `flag_unrepaired`."""

    def __init__(self, artifacts=()):
        self.doc = {"version": 7, "runtime": {}}
        self._arts = {a: {"id": a, "status": "ACTIVE"} for a in artifacts}
        self.marked: list[tuple] = []
        self.saved = 0

    def find(self, art):
        return "pages", self._arts[art]          # KeyError when it is not real

    def mark_out_of_sync(self, art, why):
        self.marked.append((art, why))

    def save(self):
        self.saved += 1


def _obs(node, subject, findings):
    return obs_mod.Observation(node=node, agent="a", subjects=[subject],
                               findings={subject: findings})


def test_a_node_level_finding_is_kept_not_dropped():
    """The 32 page_contracts findings had an empty subject and vanished."""
    svc = _Svc()
    f = Finding(edge="Reference↔Page", detail="the reference screen 'Refund Dashboard' has no page")
    assert obs_mod.flag_unrepaired(svc, _obs("page_contracts", "", [f]), "") == []
    issues = svc.doc["runtime"]["issues"]
    assert len(issues) == 1
    assert issues[0]["kind"] == "unrepaired" and issues[0]["node"] == "page_contracts"
    assert "Refund Dashboard" in issues[0]["detail"]
    assert issues[0]["version"] == 7
    assert svc.saved == 1, "a finding kept must be a finding written"


def test_a_finding_naming_a_real_artifact_still_flags_it():
    svc = _Svc(artifacts=["ENTITY-019"])
    f = Finding(edge="Data↔Database", detail="caseId samples are not uuids", artifact_id="ENTITY-019")
    assert obs_mod.flag_unrepaired(svc, _obs("entity_fields", "ENTITY-019", [f]), "ENTITY-019") == ["ENTITY-019"]
    assert svc.marked and svc.marked[0][0] == "ENTITY-019"
    assert not svc.doc["runtime"].get("issues"), "it has a home already"


def test_a_finding_naming_something_unreal_is_kept_too():
    """It used to be swallowed by the except branch."""
    svc = _Svc()
    f = Finding(edge="X↔Y", detail="about PAGE-999", artifact_id="PAGE-999")
    obs_mod.flag_unrepaired(svc, _obs("page_details", "PAGE-999", [f]), "PAGE-999")
    assert svc.doc["runtime"]["issues"][0]["detail"].endswith("about PAGE-999")


def test_re_running_a_node_replaces_its_own_entries_only():
    svc = _Svc()
    svc.doc["runtime"]["issues"] = [
        {"kind": "page_check", "page": "PAGE-001"},
        {"kind": "unrepaired", "node": "security", "subject": "", "detail": "old"},
        {"kind": "unrepaired", "node": "analytics", "subject": "", "detail": "keep me"},
    ]
    f = Finding(edge="Observer↔Requirement", detail="REQ-071 role has no permission")
    obs_mod.flag_unrepaired(svc, _obs("security", "", [f]), "")
    kinds = [(i.get("kind"), i.get("node")) for i in svc.doc["runtime"]["issues"]]
    assert ("page_check", None) in kinds, "another kind is untouched"
    assert ("unrepaired", "analytics") in kinds, "another node is untouched"
    sec = [i for i in svc.doc["runtime"]["issues"] if i.get("node") == "security"]
    assert len(sec) == 1 and "REQ-071" in sec[0]["detail"], "its own entry is replaced"


# -- 3. a repair that makes things worse stops ------------------------------

def test_more_findings_than_went_in_is_no_better():
    """The rule the orchestrator applies, stated on its own terms.

    page_contracts: 26 -> 28 -> 32 across two rounds, never 'stuck' because
    the findings differed each time, so it spent both rounds and was marked
    done. RefundExecution: 5 -> 2 -> 4 -> 5.
    """
    import inspect

    from services.blueprint import orchestrator as orch

    w = orch._Watch(subjects=["PAGE-001"])
    assert w.counts == {}, "the comparison needs somewhere to keep the previous count"

    # The branch itself lives in a closure inside `run()`, so read it: the
    # rule must be a comparison of counts, not of identity alone.
    src = inspect.getsource(orch)
    assert "len(obs.findings[subject]) > len(before)" in src, (
        "divergence must stop the loop; identity-only was how 26 -> 28 -> 32 "
        "spent both rounds and was marked done")

    def verdict(before: int, now: int) -> bool:
        """The same comparison, to state which way each case falls."""
        return now > before

    assert verdict(26, 28) and verdict(28, 32), "diverging: stop"
    assert verdict(2, 4), "RefundExecution's third round"
    assert not verdict(26, 20), "converging: keep going"
    assert not verdict(26, 26), "same count, different findings: keep going"


# -- 4. a short id is not a uuid --------------------------------------------

def test_the_rules_export_knows_a_short_id_from_a_uuid():
    from services.runtime_injector import _UUID

    assert _UUID.fullmatch("dbd8c875-71a9-4eb3-a7c4-2afc2d53c0be")
    assert not _UUID.fullmatch("kkb5mzo3"), (
        "the Blueprint path passes application.id, which is the short id; "
        "querying a uuid column with it threw and every DB rule was dropped")
