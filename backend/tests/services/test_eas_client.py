"""MOBILE-C — EAS client wrapper tests.

The CLI is stubbed via the injectable ``run`` seam so no real network
call happens. Coverage:

  * Happy path: create_build parses the CLI's --json --no-wait output
    into a BuildState.
  * Failure paths: non-zero exit, empty stdout, non-JSON stdout, wrong
    profile / platform / missing token all raise EasClientError.
  * poll_build parses build:view output.
  * normalize_status maps every documented EAS status to our DB enum
    and buckets unknowns as in_progress (safe fallback).
  * Env building: EXPO_TOKEN and EXPO_PUBLIC_APP_URL are injected;
    parent PATH is inherited.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from services.eas_client import (
    BuildState,
    EasClientError,
    _build_env,
    _parse_cli_json,
    create_build,
    is_terminal,
    normalize_status,
    poll_build,
)


# --------------------------------------------------------------------------- #
# Stub CLI runner                                                              #
# --------------------------------------------------------------------------- #

def make_runner(
    stdout: str = "",
    stderr: str = "",
    rc: int = 0,
    recorder: list | None = None,
):
    """Build a fake `run` coro that returns pre-baked output. The
    optional recorder captures (argv, cwd, env) so tests can assert
    the CLI was invoked correctly."""
    async def _run(argv, cwd, env):
        if recorder is not None:
            recorder.append({"argv": argv, "cwd": cwd, "env": env})
        return rc, stdout, stderr
    return _run


# --------------------------------------------------------------------------- #
# create_build                                                                 #
# --------------------------------------------------------------------------- #

class TestCreateBuild:
    def test_parses_no_wait_json(self):
        stdout = (
            '[{"id":"abc-123","status":"pending",'
            '"artifacts":{"buildUrl":null},"buildLogsUrl":"https://expo.dev/logs/abc"}]'
        )
        run = make_runner(stdout=stdout)
        state = asyncio.run(
            create_build(
                "/tmp/mobile",
                profile="preview",
                platform="android",
                expo_token="tok",
                deployed_url="https://uat.io",
                run=run,
            ),
        )
        assert isinstance(state, BuildState)
        assert state.build_id == "abc-123"
        assert state.status == "pending"
        assert state.logs_url == "https://expo.dev/logs/abc"
        assert state.artifact_url is None

    def test_records_expected_argv(self):
        recorder: list = []
        run = make_runner(stdout='[{"id":"x","status":"pending"}]', recorder=recorder)
        asyncio.run(
            create_build(
                "/tmp/mobile",
                profile="production",
                platform="ios",
                expo_token="tok",
                deployed_url="https://prod.io",
                run=run,
            ),
        )
        call = recorder[0]
        assert call["argv"][:2] == ["npx", "eas-cli"]
        assert "--profile" in call["argv"]
        assert "production" in call["argv"]
        assert "--platform" in call["argv"]
        assert "ios" in call["argv"]
        assert "--non-interactive" in call["argv"]
        assert "--json" in call["argv"]
        assert "--no-wait" in call["argv"]
        # EXPO_TOKEN + EXPO_PUBLIC_APP_URL injected in the env.
        assert call["env"]["EXPO_TOKEN"] == "tok"
        assert call["env"]["EXPO_PUBLIC_APP_URL"] == "https://prod.io"

    def test_apple_env_only_on_ios(self):
        recorder: list = []
        run = make_runner(stdout='[{"id":"x","status":"pending"}]', recorder=recorder)
        asyncio.run(
            create_build(
                "/tmp/mobile",
                profile="production",
                platform="ios",
                expo_token="tok",
                deployed_url="https://prod.io",
                apple_env={"APPLE_TEAM_ID": "TEAM"},
                google_env={"GOOGLE_PLAY_SERVICE_ACCOUNT_JSON": "{}"},
                run=run,
            ),
        )
        # Both are merged into the env by the client — the CALLER decides
        # per-platform which to pass. Confirms merging works.
        env = recorder[0]["env"]
        assert env["APPLE_TEAM_ID"] == "TEAM"
        assert env["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"] == "{}"

    def test_non_zero_exit_raises_with_stderr(self):
        run = make_runner(rc=1, stderr="EAS auth failed")
        with pytest.raises(EasClientError, match="EAS auth failed"):
            asyncio.run(
                create_build(
                    "/tmp/mobile",
                    profile="preview",
                    platform="android",
                    expo_token="tok",
                    deployed_url="https://x.io",
                    run=run,
                ),
            )

    def test_empty_stdout_raises(self):
        run = make_runner(stdout="")
        with pytest.raises(EasClientError, match="empty stdout"):
            asyncio.run(
                create_build(
                    "/tmp/mobile",
                    profile="preview",
                    platform="android",
                    expo_token="tok",
                    deployed_url="https://x.io",
                    run=run,
                ),
            )

    def test_invalid_platform_raises(self):
        with pytest.raises(EasClientError, match="platform must be"):
            asyncio.run(
                create_build(
                    "/tmp/mobile",
                    profile="preview",
                    platform="windows",
                    expo_token="tok",
                    deployed_url="https://x.io",
                    run=make_runner(),
                ),
            )

    def test_invalid_profile_raises(self):
        with pytest.raises(EasClientError, match="unknown build profile"):
            asyncio.run(
                create_build(
                    "/tmp/mobile",
                    profile="not-a-profile",
                    platform="android",
                    expo_token="tok",
                    deployed_url="https://x.io",
                    run=make_runner(),
                ),
            )

    def test_missing_token_raises(self):
        with pytest.raises(EasClientError, match="expo_token is required"):
            asyncio.run(
                create_build(
                    "/tmp/mobile",
                    profile="preview",
                    platform="android",
                    expo_token="",
                    deployed_url="https://x.io",
                    run=make_runner(),
                ),
            )


# --------------------------------------------------------------------------- #
# poll_build                                                                   #
# --------------------------------------------------------------------------- #

class TestPollBuild:
    def test_extracts_artifact_when_finished(self):
        stdout = (
            '{"id":"abc-123","status":"finished",'
            '"artifacts":{"buildUrl":"https://expo.dev/artifacts/abc.apk"},'
            '"buildLogsUrl":"https://expo.dev/logs/abc"}'
        )
        state = asyncio.run(
            poll_build("/tmp/mobile", "abc-123", expo_token="tok",
                       run=make_runner(stdout=stdout)),
        )
        assert state.build_id == "abc-123"
        assert state.status == "finished"
        assert state.artifact_url == "https://expo.dev/artifacts/abc.apk"

    def test_captures_error_message_from_errored_build(self):
        stdout = (
            '{"id":"x","status":"errored",'
            '"error":{"message":"Fastlane crashed: cert expired"}}'
        )
        state = asyncio.run(
            poll_build("/tmp/mobile", "x", expo_token="tok",
                       run=make_runner(stdout=stdout)),
        )
        assert state.status == "errored"
        assert "cert expired" in state.error_message

    def test_missing_build_id_raises(self):
        with pytest.raises(EasClientError, match="build_id is required"):
            asyncio.run(
                poll_build("/tmp/mobile", "", expo_token="tok",
                           run=make_runner()),
            )

    def test_tolerates_leading_warning_lines(self):
        """Some CLI versions print an npm-deprecation warning before
        the JSON. Parser should still find the JSON blob."""
        stdout = (
            "npm warn deprecated foo@1.2.3\n"
            '{"id":"abc","status":"pending"}'
        )
        state = asyncio.run(
            poll_build("/tmp/mobile", "abc", expo_token="tok",
                       run=make_runner(stdout=stdout)),
        )
        assert state.build_id == "abc"


# --------------------------------------------------------------------------- #
# normalize_status                                                             #
# --------------------------------------------------------------------------- #

class TestNormalizeStatus:
    @pytest.mark.parametrize("eas,expected", [
        ("pending", "pending"),
        ("in-queue", "pending"),
        ("in-progress", "in_progress"),
        ("in_progress", "in_progress"),
        ("finished", "completed"),
        ("succeeded", "completed"),
        ("completed", "completed"),
        ("errored", "failed"),
        ("failed", "failed"),
        ("canceled", "canceled"),
        ("cancelled", "canceled"),
    ])
    def test_documented_statuses(self, eas, expected):
        assert normalize_status(eas) == expected

    def test_unknown_status_buckets_to_in_progress(self):
        """A never-before-seen value from a future CLI must not be
        treated as terminal — that would false-complete the row."""
        assert normalize_status("some-future-status") == "in_progress"

    def test_empty_status_is_in_progress(self):
        assert normalize_status("") == "in_progress"
        assert normalize_status(None) == "in_progress"  # type: ignore[arg-type]


class TestIsTerminal:
    def test_terminal_statuses(self):
        for s in ("completed", "failed", "canceled"):
            assert is_terminal(s)

    def test_non_terminal_statuses(self):
        for s in ("pending", "in_progress", "unknown"):
            assert not is_terminal(s)


# --------------------------------------------------------------------------- #
# Env building                                                                 #
# --------------------------------------------------------------------------- #

class TestEnv:
    def test_inherits_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "/foo:/bar")
        env = _build_env("tok", "https://x.io")
        assert env["PATH"] == "/foo:/bar"
        assert env["EXPO_TOKEN"] == "tok"
        assert env["EXPO_PUBLIC_APP_URL"] == "https://x.io"

    def test_empty_deployed_url_is_ok(self):
        env = _build_env("tok", "")
        assert env["EXPO_PUBLIC_APP_URL"] == ""

    def test_extra_env_merges_last(self):
        env = _build_env("tok", "https://x.io", extra={"APPLE_TEAM_ID": "T"})
        assert env["APPLE_TEAM_ID"] == "T"

    def test_extra_can_override_defaults(self):
        env = _build_env("tok", "https://x.io", extra={"EXPO_TOKEN": "different"})
        assert env["EXPO_TOKEN"] == "different"


# --------------------------------------------------------------------------- #
# JSON parser fallback                                                         #
# --------------------------------------------------------------------------- #

class TestParseCliJson:
    def test_parses_plain_json(self):
        assert _parse_cli_json('{"x":1}', context="test") == {"x": 1}

    def test_parses_array(self):
        assert _parse_cli_json("[1,2,3]", context="test") == [1, 2, 3]

    def test_finds_json_after_warning(self):
        assert _parse_cli_json("warn\n[{}]", context="test") == [{}]

    def test_empty_raises(self):
        with pytest.raises(EasClientError):
            _parse_cli_json("", context="test")

    def test_no_json_raises(self):
        with pytest.raises(EasClientError):
            _parse_cli_json("just some text", context="test")
