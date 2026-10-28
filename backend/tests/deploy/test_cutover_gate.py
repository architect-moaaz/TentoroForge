"""The cutover gate sees what is under way, and a question it cannot answer is busy.

`deploy/v3-cutover.sh`'s publish check put `$since` inside a single-quoted
`sh -c`, so the timestamp reached the container empty, the SQL failed, and
`|| echo 0` read the failure as "nothing under way": the gate never saw a
publish (2026-10-26). These run the gate's own `busy` against a stand-in
`docker` on PATH.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "v3-cutover.sh"

FAKE_DOCKER = r"""#!/bin/bash
# Logs each call and its stdin; answers as the test's FAKE_* variables say.
log="$FAKE_LOG"
if [ "$1" = "inspect" ]; then echo "$FAKE_STARTED"; exit 0; fi
if [ "$1" = "exec" ]; then
  if [ "$2" = "-i" ]; then
    sql=$(cat)
    printf '%s\n' "$*" >> "$log"; printf 'SQL: %s\n' "$sql" >> "$log"
    [ "${FAKE_PG_FAIL:-0}" = "1" ] && { echo "ERROR: boom" >&2; exit 1; }
    echo "${FAKE_PUBLISHES:-0}"; exit 0
  fi
  printf '%s\n' "$*" >> "$log"
  echo "${FAKE_REVIEW:-0}"; exit 0
fi
exit 0
"""

FAKE_STAT = r"""#!/bin/bash
# GNU `stat -c %Y FILE` on any system.
if [ "$1" = "-c" ] && [ "$2" = "%Y" ]; then python3 -c 'import os,sys; print(int(os.path.getmtime(sys.argv[1])))' "$3"; exit 0; fi
exec /usr/bin/stat "$@"
"""


@pytest.fixture
def gate(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("stat", FAKE_STAT)):
        f = bin_ / name
        f.write_text(body)
        f.chmod(0o755)
    root = tmp_path / "v3"
    (root / "data" / "output").mkdir(parents=True)
    log = tmp_path / "docker.log"
    log.write_text("")

    def run(**env: str) -> tuple[int, str]:
        e = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "V3_ROOT": str(root), "FAKE_LOG": str(log),
             "FAKE_STARTED": "2026-10-26T08:52:02.167081983Z", **env}
        r = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; busy'], env=e, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    run.root, run.log = root, log  # type: ignore[attr-defined]
    return run


def test_an_idle_platform_is_not_busy(gate):
    code, out = gate()
    assert code == 0, out


def test_the_backends_start_time_reaches_the_publish_query(gate):
    gate()
    sql = [l for l in gate.log.read_text().splitlines() if l.startswith("SQL: ")]
    assert sql and "created_at > '2026-10-26T08:52:02.167081983Z'" in sql[0], sql


def test_a_publish_under_way_is_busy(gate):
    code, out = gate(FAKE_PUBLISHES="1")
    assert code == 1 and "1 publish(es) under way" in out


def test_a_platform_database_that_cannot_answer_is_busy(gate):
    code, out = gate(FAKE_PG_FAIL="1")
    assert code == 1 and "could not ask the platform database" in out


def test_a_review_database_in_use_is_busy(gate):
    code, out = gate(FAKE_REVIEW="2")
    assert code == 1 and "2 review/trial database(s) in use" in out


def test_a_ledger_still_writing_is_busy_and_a_finished_one_is_not(gate):
    runs = gate.root / "data" / "output" / "abc12345" / ".forge" / "runs"
    runs.mkdir(parents=True)
    done = runs / "20261026-1-build.jsonl"
    done.write_text(json.dumps({"event": "run:start"}) + "\n" + json.dumps({"event": "run:end"}) + "\n")
    assert gate()[0] == 0
    live = runs / "20261026-2-turn.jsonl"
    live.write_text(json.dumps({"event": "run:start"}) + "\n")
    code, out = gate()
    assert code == 1 and "abc12345/20261026-2-turn" in out
    old = time.time() - 600
    os.utime(live, (old, old))
    assert gate()[0] == 0, "a ledger silent for ten minutes is not alive"
