"""An app is published to Test or to Production, and a Test publish never
touches production: its own Vercel preview at a fixed address, its own empty
database with demo data, its own settings (test payment keys or none, email
only to the organisation), and a promote that sends exactly the tested files
to production. Vercel and Neon are stand-ins; the database is the test one."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from models.deployment import Deployment
from services.deploy import environments as envs
from services.deploy.provider import DeploySnapshot
from services.deploy.vercel_provider import VercelDeployProvider
from tests.deploy.test_vercel_provider import (  # noqa: F401 — fixtures
    _mk_app_tree, _mock_neon_client, _mock_vercel_client, db_session, sample_project_id)


def _vercel(**over: Any):
    m = _mock_vercel_client()
    m.alias_deployment.return_value = {}
    m.redeploy.return_value = {"id": "dpl_prod", "url": "acme-prod.vercel.app"}
    m.set_env_target.return_value = {}
    # An app whose production side has a version that built; a first publish
    # is said so by the test that is about it.
    m.get_project.return_value = {"id": "prj_1", "targets": {"production": {"readyState": "READY"}}}
    for k, v in over.items():
        setattr(m, k, v)
    return m


def _neon(created: bool = True):
    m = _mock_neon_client()
    m.ensure_database.return_value = {"database_url": "postgres://u:p@ep.neon.tech/forge_test",
                                      "created": created, "branch_id": "br_1"}
    m.get_connection_uri.return_value = "postgres://u:p@ep.neon.tech/neondb"
    m.drop_database.return_value = True
    return m


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    async def ok(url):
        return True, None
    monkeypatch.setattr("services.deploy.vercel_provider._smoke_test_db", ok)
    attached: list = []

    async def attach(*a, **k):
        attached.append(a)
        return []
    monkeypatch.setattr("services.deploy.domains.attach_after_publish", attach)
    monkeypatch.setattr("services.deploy.vendor_refresh.refresh_vendor_and_deps", lambda *a, **k: None)
    return attached


def _pushed(vercel) -> dict[str, tuple[str, list]]:
    out = {}
    for c in vercel.set_env.call_args_list:
        _pid, key, val, targets = c.args[:4]
        out[key] = (val, targets)
    return out


async def _publish(db, project_id, tmp_path, vercel, neon, **snap):
    provider = VercelDeployProvider(db=db, vercel=vercel, neon=neon)
    s = DeploySnapshot(project_id=str(project_id), project_slug="acme", output_dir=str(tmp_path), **snap)
    return [e async for e in provider.publish(s)]


async def _rows(db, project_id):
    db.expire_all()
    res = await db.execute(select(Deployment).where(Deployment.project_id == project_id)
                           .order_by(Deployment.created_at))
    return res.scalars().all()


# --------------------------------------------------------------------------- #
# The pieces
# --------------------------------------------------------------------------- #

def test_each_side_gets_its_own_keys():
    org = {"STRIPE_SECRET_KEY": "sk_l", "STRIPE_TEST_SECRET_KEY": "sk_t", "STRIPE_PUBLISHABLE_KEY": "pk_l",
           "TWILIO_AUTH_TOKEN": "tw", "RESEND_API_KEY": "re"}
    prod = envs.integrations_for(envs.PRODUCTION, org)
    assert prod == {"STRIPE_SECRET_KEY": "sk_l", "STRIPE_PUBLISHABLE_KEY": "pk_l", "TWILIO_AUTH_TOKEN": "tw",
                    "RESEND_API_KEY": "re"}, "production as stored, never the test twins"
    test = envs.integrations_for(envs.TEST, org)
    assert test == {"STRIPE_SECRET_KEY": "sk_t", "RESEND_API_KEY": "re"}, \
        "test: the test twin, money keys without one dropped (the stand-in pays), SMS never"
    assert envs.side_settings(envs.TEST, test_recipients=["B@x.com", "a@x.com", ""]) == \
        {"FORGE_ENVIRONMENT": "test", "FORGE_TEST_RECIPIENTS": "a@x.com,b@x.com"}
    assert envs.side_settings(envs.PRODUCTION) == {"FORGE_ENVIRONMENT": "production"}
    assert envs.test_alias("acme") == "acme-test.vercel.app"
    assert envs.vercel_target(envs.TEST) is None and envs.env_targets(envs.TEST) == ["preview"]
    with pytest.raises(ValueError):
        envs.normalise("staging")


def test_the_fingerprint_now_is_the_one_a_publish_records(tmp_path):
    from services.deploy.snapshot import build_snapshot_upload, snapshot_digest
    _mk_app_tree(tmp_path)
    assert snapshot_digest(tmp_path) == envs.source_digest(build_snapshot_upload(tmp_path))
    before = snapshot_digest(tmp_path)
    (tmp_path / "src" / "page.tsx").write_text("export default () => 1;")
    assert snapshot_digest(tmp_path) != before


def test_an_older_app_gets_the_test_ribbon_once(tmp_path):
    from services.deploy.vercel_provider import _ensure_test_ribbon
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text('import "./globals.css";\nexport default function L({children}) {\n'
                      '  return <html><body suppressHydrationWarning>\n        <Providers>{children}</Providers>'
                      '</body></html>;\n}\n')
    assert _ensure_test_ribbon(tmp_path) is True
    text = layout.read_text()
    assert text.startswith('import { TestRibbon } from "@/components/TestRibbon";')
    assert "<body suppressHydrationWarning>\n        <TestRibbon />" in text
    assert _ensure_test_ribbon(tmp_path) is False, "once"


_OLD_LAYOUT = (
    'import "./globals.css";\n'
    "export default function RootLayout({ children }) {\n"
    "  return (\n"
    "    // suppressHydrationWarning: browser extensions (Grammarly, ColorZilla, Scribe…)\n"
    "    // inject attributes onto <html>/<body> before React hydrates; without this they\n"
    "    // trip a benign hydration-mismatch warning. Scoped to these tags only.\n"
    '    <html lang="en" dir="ltr" suppressHydrationWarning>\n'
    "      <body suppressHydrationWarning>\n"
    "        <Providers>{children}</Providers>\n"
    "      </body>\n"
    "    </html>\n"
    "  );\n"
    "}\n"
)


def test_the_ribbon_goes_in_the_body_tag_not_a_body_named_in_a_comment(tmp_path):
    """Mark 8 (cxz95dd1, 2026-10-16): the ribbon was put after the `<body>`
    in the comment above the markup, and every build failed to compile."""
    from services.deploy.vercel_provider import _ensure_test_ribbon
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text(_OLD_LAYOUT)
    assert _ensure_test_ribbon(tmp_path) is True
    text = layout.read_text()
    assert "onto <html>/<body> before React hydrates; without this they\n" in text
    assert "<body suppressHydrationWarning>\n        <TestRibbon />\n        <Providers>" in text
    assert text.count("<TestRibbon />") == 1


def test_a_ribbon_once_put_into_a_comment_is_taken_back_out(tmp_path):
    from services.deploy.vercel_provider import _ensure_test_ribbon
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    broken = 'import { TestRibbon } from "@/components/TestRibbon";\n' + _OLD_LAYOUT.replace(
        "onto <html>/<body> before", "onto <html>/<body>\n        <TestRibbon /> before")
    layout.write_text(broken)
    assert _ensure_test_ribbon(tmp_path) is True
    text = layout.read_text()
    assert "onto <html>/<body> before React hydrates" in text
    assert "<body suppressHydrationWarning>\n        <TestRibbon />" in text
    assert text.count("<TestRibbon />") == 1 and text.count("import { TestRibbon }") == 1
    assert _ensure_test_ribbon(tmp_path) is False, "once"


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_test_publish_never_touches_production(db_session, sample_project_id, tmp_path, _quiet,
                                                       monkeypatch):
    _mk_app_tree(tmp_path)
    tried = []

    async def trial(*a, **k):
        tried.append(a)
        return {"ok": True, "fixed": False}
    monkeypatch.setattr("services.deploy.migration_trial.ensure_publishable", trial)
    vercel, neon = _vercel(), _neon(created=True)
    events = await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="test",
                            integrations={"STRIPE_SECRET_KEY": "sk_l", "RESEND_API_KEY": "re"},
                            test_recipients=("owner@acme.com",))
    assert events[-1].stage == "done" and events[-1].data["environment"] == "test"
    assert events[-1].message.startswith("Test version live at https://acme-test.vercel.app")
    assert vercel.create_deployment.call_args.kwargs["target"] is None, "a preview, not production"
    pushed = _pushed(vercel)
    assert all(t == ["preview"] for _, t in pushed.values()), "every setting on the test side only"
    assert pushed["DATABASE_URL"][0].endswith("/forge_test"), "its own database"
    assert pushed["FORGE_ENVIRONMENT"][0] == "test" and pushed["FORGE_TEST_RECIPIENTS"][0] == "owner@acme.com"
    assert pushed["NEXTAUTH_URL"][0] == "https://acme-test.vercel.app"
    assert "STRIPE_SECRET_KEY" not in pushed, "no live money key on the test side"
    assert "FORGE_KEEP_DB_STATE" not in pushed, "a new test database is seeded with demo data"
    neon.ensure_database.assert_awaited_once_with("np_123", "forge_test")
    vercel.alias_deployment.assert_awaited_once_with("dpl_xyz", "acme-test.vercel.app")
    assert tried == [] and _quiet == [], "no live-data trial, no production domains"
    vercel.disable_deployment_protection.assert_awaited()
    (row,) = await _rows(db_session, sample_project_id)
    assert (row.environment, row.status, row.url) == ("test", "succeeded", "https://acme-test.vercel.app")
    assert row.source_digest and len(row.source_digest) == 64


@pytest.mark.asyncio
async def test_a_second_test_publish_keeps_what_testers_entered(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    await _publish(db_session, sample_project_id, tmp_path, _vercel(), _neon(created=True), environment="test")
    vercel, neon = _vercel(), _neon(created=False)
    await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="test")
    assert _pushed(vercel)["FORGE_KEEP_DB_STATE"][0] == "1"
    neon.create_project.assert_not_called()


@pytest.mark.asyncio
async def test_starting_the_test_data_again(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    await _publish(db_session, sample_project_id, tmp_path, _vercel(), _neon(), environment="test")
    neon = _neon(created=True)
    events = await _publish(db_session, sample_project_id, tmp_path, _vercel(), neon, environment="test",
                            reset_test_data=True)
    neon.drop_database.assert_awaited_once_with("np_123", "forge_test")
    assert any("demo data" in e.message for e in events)


@pytest.mark.asyncio
async def test_production_after_test_uses_the_live_database_and_production_settings(
        db_session, sample_project_id, tmp_path, _quiet, monkeypatch):
    _mk_app_tree(tmp_path)
    tried = []

    async def trial(neon, project_id, *a, **k):
        tried.append(project_id)
        return {"ok": True, "fixed": False}
    monkeypatch.setattr("services.deploy.migration_trial.ensure_publishable", trial)
    await _publish(db_session, sample_project_id, tmp_path, _vercel(), _neon(), environment="test")
    vercel, neon = _vercel(), _neon()
    await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="production",
                   integrations={"STRIPE_SECRET_KEY": "sk_l", "STRIPE_TEST_SECRET_KEY": "sk_t"})
    assert tried == [], "production has never run: nothing live to try the change on"
    assert vercel.create_deployment.call_args.kwargs["target"] == "production"
    pushed = _pushed(vercel)
    assert all(t == ["production"] for _, t in pushed.values())
    assert pushed["DATABASE_URL"][0].endswith("/neondb"), "the live database, not the test one"
    assert pushed["STRIPE_SECRET_KEY"][0] == "sk_l" and "STRIPE_TEST_SECRET_KEY" not in pushed
    assert pushed["FORGE_ENVIRONMENT"][0] == "production" and "FORGE_TEST_RECIPIENTS" not in pushed
    neon.ensure_database.assert_not_called()
    vercel.alias_deployment.assert_not_called()
    assert len(_quiet) == 1, "production's domains are attached"
    rows = await _rows(db_session, sample_project_id)
    assert [r.environment for r in rows] == ["test", "production"]
    # and the next production publish asks the live data first
    await _publish(db_session, sample_project_id, tmp_path, _vercel(), _neon(), environment="production")
    assert tried == ["np_123"]


@pytest.mark.asyncio
async def test_a_setting_shared_with_production_is_split_before_the_test_side_writes(
        db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel = _vercel()
    vercel.list_env.return_value = [{"id": "env_shared", "key": "FOO", "target": ["production", "preview"]}]
    await _publish(db_session, sample_project_id, tmp_path, vercel, _neon(), environment="test")
    vercel.set_env_target.assert_awaited_once_with("prj_abc", "env_shared", ["production"])
    assert all(c.args[1] != "env_shared" for c in vercel.update_env.call_args_list), \
        "the shared row is never rewritten by the test side"


@pytest.mark.asyncio
async def test_promote_sends_exactly_the_tested_files_to_production(db_session, sample_project_id, tmp_path, _quiet):
    _mk_app_tree(tmp_path)
    await _publish(db_session, sample_project_id, tmp_path, _vercel(), _neon(), environment="test")
    (test_row,) = await _rows(db_session, sample_project_id)
    (tmp_path / "src" / "page.tsx").write_text("export default () => 'edited after testing';")
    vercel, neon = _vercel(), _neon()
    vercel.get_deployment.return_value = {"readyState": "READY", "url": "acme-prod.vercel.app"}
    events = await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="production",
                            promote_from=str(test_row.id))
    assert events[-1].stage == "done"
    vercel.redeploy.assert_awaited_once_with("acme", "dpl_xyz", target="production")
    vercel.upload_file.assert_not_called()
    vercel.create_deployment.assert_not_called()
    assert all(t == ["production"] for _, t in _pushed(vercel).values())
    rows = await _rows(db_session, sample_project_id)
    prod = rows[-1]
    assert (prod.environment, prod.promoted_from, prod.source_digest) == \
        ("production", test_row.id, test_row.source_digest), "the tested files, not the later edit"


@pytest.mark.asyncio
async def test_nothing_to_promote_changes_nothing(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel = _vercel()
    events = await _publish(db_session, sample_project_id, tmp_path, vercel, _neon(), environment="production",
                            promote_from=str(uuid.uuid4()))
    assert events[-1].stage == "error" and "not live" in events[-1].message
    vercel.redeploy.assert_not_called()
    vercel.create_deployment.assert_not_called()


# --------------------------------------------------------------------------- #
# Elsewhere
# --------------------------------------------------------------------------- #

def test_new_apps_start_on_test_and_old_ones_stay_on_production():
    from models.project import Project
    col = Project.__table__.c.publish_target
    assert col.default.arg == "test" and col.server_default.arg == "production"
    dep = Deployment.__table__.c.environment
    assert dep.server_default.arg == "production"


def test_the_test_version_emails_only_the_organisation_and_says_so():
    src = (Path(__file__).resolve().parents[2] / "templates/runtime/workflows/index.ts").read_text()
    assert 'process.env.FORGE_ENVIRONMENT === "test"' in src and "FORGE_TEST_RECIPIENTS" in src
    assert "if (smtpHost && sendTo)" in src and "if (key && sendTo)" in src
    assert "emails only your organisation's members" in src
    ribbon = (Path(__file__).resolve().parents[2] / "templates/app-foundation/src/components/TestRibbon.tsx").read_text()
    assert 'process.env.FORGE_ENVIRONMENT !== "test"' in ribbon and "noindex" in ribbon
    layout = (Path(__file__).resolve().parents[2] / "templates/app-foundation/src/app/layout.tsx").read_text()
    assert "<TestRibbon />" in layout


def test_a_domain_change_never_touches_the_test_versions_settings(tmp_path):
    """The main domain going live re-points the live app's sign-in address;
    the test version's own NEXTAUTH_URL row is left as it is."""
    import asyncio
    from tests.services.test_an_app_answers_at_its_own_address import FakeVercel, _project, _service
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.add("app.acme.com")
    test_rows = [{"id": "env_test_url", "key": "NEXTAUTH_URL", "value": "https://aqua-test.vercel.app",
                  "target": ["preview"]}]
    original = fake.list_env

    async def list_env(pid):
        return [*test_rows, *(await original(pid))]
    fake.list_env = list_env
    svc = _service(root, fake)
    asyncio.run(svc.connect("app.acme.com"))
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://app.acme.com"
    assert "env_test_url" not in fake.env, "the test version's row was never updated"


def test_the_live_app_is_shown_at_its_main_address_once_it_answers(tmp_path):
    """While the Tentoro address is still waiting, the live app is shown at its
    Vercel address (""); once it answers, at `<app>.apps.tentoro.ai`; once the
    owner's own main domain answers, at that."""
    from services.blueprint.service import BlueprintService
    from services.deploy.domains import live_address
    svc = BlueprintService.create(output_dir=tmp_path, app_id="aqua", name="AquaTrack", domain="health")
    svc.doc["deployment"] = {"domains": [{"name": "aqua.apps.tentoro.ai", "kind": "tentoro", "main": True,
                                          "status": "waiting"}]}
    svc.save()
    assert live_address(tmp_path, "aqua") == ""
    svc.doc["deployment"]["domains"][0]["status"] = "live"
    svc.save()
    assert live_address(tmp_path, "aqua") == "https://aqua.apps.tentoro.ai"
    svc.doc["deployment"]["domains"][0]["main"] = False
    svc.doc["deployment"]["domains"].append({"name": "app.acme.com", "kind": "subdomain", "main": True,
                                             "status": "live"})
    svc.save()
    assert live_address(tmp_path, "aqua") == "https://app.acme.com"
    assert live_address(None, "aqua") == ""


# --- a first publish, to Test ------------------------------------------------
# Vercel makes a project's first deployment its production one whatever the
# request says; Personal Finance's first publish, to Test, was built without its
# test settings — "[reset-schema] DATABASE_URL missing" (u8w3uw4j, 2026-10-21).

@pytest.mark.asyncio
async def test_a_first_test_publish_gives_both_sides_the_test_settings(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel = _vercel()
    vercel.get_project.return_value = {"id": "prj_1", "targets": {}}
    events = await _publish(db_session, sample_project_id, tmp_path, vercel, _neon(created=True), environment="test")
    assert events[-1].stage == "done"
    pushed = _pushed(vercel)
    assert all(sorted(t) == ["preview", "production"] for _, t in pushed.values()), "whichever side Vercel builds"
    assert pushed["DATABASE_URL"][0].endswith("/forge_test"), "still the test database"


@pytest.mark.asyncio
async def test_after_a_failed_first_build_the_rows_are_widened_and_duplicates_go(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel = _vercel()
    vercel.get_project.return_value = {"id": "prj_1", "targets": {"production": {"readyState": "ERROR"}}}
    vercel.list_env.return_value = [
        {"id": "e1", "key": "DATABASE_URL", "target": ["preview"]},
        {"id": "e2", "key": "DATABASE_URL", "target": ["production"]},
    ]
    await _publish(db_session, sample_project_id, tmp_path, vercel, _neon(created=False), environment="test")
    widened = [c for c in vercel.update_env.call_args_list if c.args[1] == "e1"]
    assert widened and sorted(widened[0].args[3]) == ["preview", "production"]
    assert [c.args[1] for c in vercel.delete_env.call_args_list] == ["e2"], "the second row of the name goes"
    assert "DATABASE_URL" not in _pushed(vercel), "updated in place, not written twice"


@pytest.mark.asyncio
async def test_once_production_has_built_a_test_publish_is_the_test_sides_alone(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel = _vercel()   # production READY
    await _publish(db_session, sample_project_id, tmp_path, vercel, _neon(created=True), environment="test")
    assert all(t == ["preview"] for _, t in _pushed(vercel).values())
