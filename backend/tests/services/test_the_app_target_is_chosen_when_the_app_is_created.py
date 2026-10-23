"""A website that works on phones, or a website AND a mobile app: chosen when the app is created.

The "Describe Your App" dialog sends `mobile_target`. It is kept beside the Blueprint-to-be and becomes
`mobile.native.enabled` when the Blueprint is created, an explicit False for `responsive` so the server's own
default can never start the native agent for an app whose owner asked for a website."""
from __future__ import annotations

import json

import pytest

from services.blueprint import app_target
from services.blueprint.native_projection import enabled
from services.blueprint.orchestrator import native_page_subjects
from services.blueprint.service import BlueprintService
from schemas.project import ProjectCreate


def made(tmp_path, target):
    if target:
        app_target.write(tmp_path, target)
    return BlueprintService.create(output_dir=tmp_path, app_id="x", name="Paws", domain="clinic", description="d")


def test_a_native_choice_turns_the_mobile_app_on(tmp_path):
    svc = made(tmp_path, "native")
    assert svc.doc["mobile"]["native"]["enabled"] is True and enabled(svc.doc)
    assert json.loads((tmp_path / ".forge/blueprint/current.json").read_text("utf-8"))["mobile"]["native"]["enabled"] is True


def test_a_responsive_choice_is_an_explicit_no(tmp_path):
    svc = made(tmp_path, "responsive")
    assert svc.doc["mobile"]["native"]["enabled"] is False
    assert not enabled(svc.doc) and native_page_subjects(svc.doc) == [], "the native agent does not run"


def test_an_app_created_before_the_choice_existed_stays_a_website(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_NATIVE_APP", "1")           # no longer read: nothing but the Blueprint turns native on
    svc = made(tmp_path, None)
    assert app_target.read(tmp_path) is None and not enabled(svc.doc) and native_page_subjects(svc.doc) == []


def test_anything_but_the_two_choices_is_ignored(tmp_path):
    assert app_target.write(tmp_path, "both") is False and app_target.read(tmp_path) is None
    (tmp_path / ".forge").mkdir(exist_ok=True)
    (tmp_path / app_target.FILE).write_text("not json", "utf-8")
    assert app_target.read(tmp_path) is None


def test_the_create_request_takes_only_the_two_choices():
    assert ProjectCreate(name="x").mobile_target is None
    assert ProjectCreate(name="x", mobile_target="native").mobile_target == "native"
    with pytest.raises(Exception):
        ProjectCreate(name="x", mobile_target="ios-only")


def test_the_project_keeps_the_choice_beside_its_blueprint(tmp_path, monkeypatch):
    import asyncio
    import uuid

    from services import project_service

    monkeypatch.setattr(project_service, "OUTPUT_BASE", tmp_path)

    class Db:
        def add(self, obj):
            self.obj = obj

        async def flush(self):
            pass

        async def refresh(self, obj):
            pass

    async def run():
        import services.git_service as git
        git.git_init = lambda path: asyncio.sleep(0)
        return await project_service.create_project(uuid.uuid4(), uuid.uuid4(), "Paws", None, Db(), mobile_target="native")

    project = asyncio.run(run())
    assert app_target.read(project.output_dir) == "web_native"      # the dialog's old "native" is read as what it meant


def test_a_native_app_made_from_the_dialog_passes_the_contracts_own_mobile_check(tmp_path):
    """The first real build failed its requirements step: the contract refuses `mobile.native` without a bundle id."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, check_mobile

    svc = made(tmp_path, "native")
    assert svc.doc["mobile"]["store"]["bundleId"] == "com.tentoro.paws"
    result = AgentResult(task_id="t", agent="requirements_analyst",
                         proposals=[ArtifactProposal(section="requirements", natural_key="REQ-001", body={})])
    check_mobile(result, svc.doc)          # raises InvalidMobile when the app is not buildable


def test_the_bundle_id_is_made_from_the_name_and_always_valid():
    import re
    from services.blueprint.app_target import bundle_for
    valid = re.compile(r"^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)+$")
    for name, expect in [("Leafy", "com.tentoro.leafy"), ("Paws & Co", "com.tentoro.pawsco"), ("123 Go", "com.tentoro.app123go"),
                         ("", "com.tentoro.app"), ("   ", "com.tentoro.app")]:
        assert bundle_for(name) == expect and valid.match(bundle_for(name))


def test_an_owners_own_bundle_id_is_kept(tmp_path):
    from services.blueprint.app_target import apply
    doc = {"application": {"name": "X"}, "mobile": {"store": {"bundleId": "org.acme.thing"}}}
    assert apply(doc, "native")["mobile"]["store"]["bundleId"] == "org.acme.thing"
    assert "store" not in apply({"application": {"name": "X"}}, "responsive")["mobile"]
