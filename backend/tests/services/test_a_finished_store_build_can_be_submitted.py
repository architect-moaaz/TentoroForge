"""A finished production build is sent to its store with `eas submit`, from a staged copy that holds the keys."""
from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from routers import mobile_builds as mb
from services import eas_client, native_build
from services.mobile_credentials import AppleAscCredentials


def project(tmp_path):
    root = tmp_path / "native"
    root.mkdir()
    (root / "app.json").write_text("{}", "utf-8")
    (root / "eas.json").write_text(json.dumps({"submit": {"production": {"android": {"track": "internal"}, "ios": {}}}}), "utf-8")
    return root


APPLE = AppleAscCredentials(team_id="T1", key_id="K1", issuer_id="I1", private_key="-----P8-----", app_id="123456")


def test_the_android_key_is_written_beside_the_project_and_named_in_the_submit_profile(tmp_path):
    root = project(tmp_path)
    native_build.write_submit_keys(root, "android", google_json='{"type":"service_account"}')
    config = json.loads((root / "eas.json").read_text("utf-8"))
    android = config["submit"]["production"]["android"]
    assert android["serviceAccountKeyPath"] == "./play-key.json" and android["track"] == "internal", "the track already there is kept"
    assert (root / "play-key.json").read_text("utf-8") == '{"type":"service_account"}'


def test_the_ios_key_and_ids_are_written_for_a_submit_that_cannot_be_asked(tmp_path):
    root = project(tmp_path)
    native_build.write_submit_keys(root, "ios", apple=APPLE)
    ios = json.loads((root / "eas.json").read_text("utf-8"))["submit"]["production"]["ios"]
    assert ios == {"ascApiKeyPath": "./asc-key.p8", "ascApiKeyId": "K1", "ascApiKeyIssuerId": "I1", "appleTeamId": "T1", "ascAppId": "123456"}
    assert (root / "asc-key.p8").read_text("utf-8") == "-----P8-----"


def test_a_missing_key_is_said_not_submitted_around(tmp_path):
    root = project(tmp_path)
    with pytest.raises(native_build.NativeBuildError, match="Google Play"):
        native_build.write_submit_keys(root, "android", google_json="")
    with pytest.raises(native_build.NativeBuildError, match="APPLE_ASC_APP_ID"):
        native_build.write_submit_keys(root, "ios", apple=AppleAscCredentials(team_id="T", key_id="K", issuer_id="I", private_key="P"))


def test_the_submit_command_names_the_build_the_store_profile_and_never_asks(tmp_path):
    seen = {}

    async def run(argv, cwd, env):
        seen.update(argv=argv, cwd=cwd, env=env)
        return 0, "Submitted. https://expo.dev/submissions/x\n", ""

    said = asyncio.run(eas_client.submit_build(str(tmp_path), build_id="b-1", platform="android", expo_token="tok", extra_env=eas_client.NO_VCS, run=run))
    assert seen["argv"][:5] == ["npx", "eas-cli", "submit", "--platform", "android"]
    assert "--id" in seen["argv"] and "b-1" in seen["argv"] and "--non-interactive" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--profile") + 1] == "production"
    assert seen["env"]["EXPO_TOKEN"] == "tok" and seen["env"]["EAS_NO_VCS"] == "1"
    assert "expo.dev/submissions" in said


def test_a_refused_submit_says_what_the_store_step_said(tmp_path):
    async def run(argv, cwd, env):
        return 1, "", "warn\nGoogle Api Error: The caller does not have permission"

    with pytest.raises(eas_client.EasClientError, match="does not have permission"):
        asyncio.run(eas_client.submit_build(str(tmp_path), build_id="b", platform="android", expo_token="t", run=run))


def runner(tmp_path, monkeypatch, submit):
    marks = []

    async def mark(row_id, status, message):
        marks.append((status, message))

    seen = {}

    async def fake_submit(staged, **kw):
        seen["staged"] = staged
        seen["files"] = sorted(p.name for p in Path(staged).iterdir())
        return await submit(kw)

    monkeypatch.setattr(mb, "_mark_submit", mark)
    monkeypatch.setattr(mb, "submit_build", fake_submit)
    creds = types.SimpleNamespace(expo_eas_token="tok", google=types.SimpleNamespace(service_account_json="{}"), apple=APPLE)
    return marks, seen, creds


def test_a_submit_runs_in_a_staged_copy_with_the_key_and_the_key_is_gone_afterwards(tmp_path, monkeypatch):
    root = project(tmp_path)

    async def ok(kw):
        return "Done."

    marks, seen, creds = runner(tmp_path, monkeypatch, ok)
    asyncio.run(mb._run_submit("row", str(root), "b-1", "android", creds))
    assert "play-key.json" in seen["files"], "the key is in the folder EAS submits from"
    assert not Path(seen["staged"]).exists(), "and the folder, key and all, is removed afterwards"
    assert not (root / "play-key.json").exists(), "the real project never holds a key"
    assert marks == [("submitted", "Sent to Google Play (Internal testing). Done.")]


def test_a_failed_submit_is_written_on_the_row_and_still_cleans_up(tmp_path, monkeypatch):
    root = project(tmp_path)

    async def refused(kw):
        raise eas_client.EasClientError("eas submit exited 1: app not found")

    marks, seen, creds = runner(tmp_path, monkeypatch, refused)
    asyncio.run(mb._run_submit("row", str(root), "b-1", "ios", creds))
    assert marks == [("submit_failed", "eas submit exited 1: app not found")]
    assert not Path(seen["staged"]).exists()


def test_a_submit_with_no_key_fails_before_anything_is_run(tmp_path, monkeypatch):
    root = project(tmp_path)

    async def never(kw):
        raise AssertionError("must not run")

    marks, seen, creds = runner(tmp_path, monkeypatch, never)
    creds.google = types.SimpleNamespace(service_account_json="")
    asyncio.run(mb._run_submit("row", str(root), "b-1", "android", creds))
    assert marks and marks[0][0] == "submit_failed" and "Google Play" in marks[0][1]
    assert "staged" not in seen
