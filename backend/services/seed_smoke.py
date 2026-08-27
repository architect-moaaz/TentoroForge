"""Optional build-time seed-smoke gate.

The whole point of the CRUD-correctness pass is that a generated app *works* the
moment it boots. The single loudest failure mode is a schema/seed mismatch — a
`users.password` column the auth code expects but the schema dropped, or a uuid
PK/FK class mismatch — which Postgres only surfaces when `seed.ts` actually runs.
That happens on the user's first `start.sh`, not during generation, so a broken
app ships green.

This helper closes that gap: run the generated app's OWN `start.sh --seed-only`
(boot Docker Postgres + migrate + seed, then stop) and treat any seed/migration
error as a LOUD generation warning. It is:

  * OFF by default — gated behind the `FORGE_SEED_SMOKE` env flag — because it
    needs Docker and adds ~1-2 min to a generation; CI and every routine gen
    skip it entirely.
  * Non-fatal — a failure is reported, never crashes the pipeline (unless the
    caller opts in to hard-fail).

`start.sh --seed-only` prints a `SEEDED_OK` sentinel on success and keeps going
(exit 0) even when seeding fails, so success is judged by BOTH a clean exit and
the sentinel AND the absence of error markers — not the exit code alone.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

FLAG_ENV = "FORGE_SEED_SMOKE"
_SENTINEL = "SEEDED_OK"
_DEFAULT_TIMEOUT = 180

# Substrings that mark a real seed/migration failure in the captured output.
_ERROR_MARKERS = (
    "postgreserror",
    "seeding failed",
    "does not exist",
    "violates",
    "relation ",
    "syntaxerror",
    "econnrefused",
    "migration failed",
    "error:",
    "fatal",
)


def is_enabled() -> bool:
    """True when the FORGE_SEED_SMOKE flag is set to a truthy value."""
    return str(os.environ.get(FLAG_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _scan_errors(output: str) -> list[str]:
    """Lines from the output that match a known seed/migration error marker."""
    hits: list[str] = []
    for line in output.splitlines():
        low = line.lower()
        if any(m in low for m in _ERROR_MARKERS):
            hits.append(line.strip())
    return hits


# `seed.ts` (P0-B) prints, per table it planned to seed:
#   ✅ seeded 8/8 users          (inserted/planned)
#   ❌ SEED MISMATCH: orders planned 8 inserted 0
# A domain table that planned rows (planned > 0) but landed zero is a silent
# empty-table defect the SEEDED_OK sentinel alone would let ship green.
_MISMATCH_RE = re.compile(
    r"SEED MISMATCH:\s*(?P<table>\S+)\s+planned\s+(?P<planned>\d+)\s+inserted\s+(?P<inserted>\d+)",
    re.IGNORECASE,
)
_SEEDED_RE = re.compile(
    r"seeded\s+(?P<inserted>\d+)\s*/\s*(?P<planned>\d+)\s+(?P<table>\S+)",
    re.IGNORECASE,
)


def detect_seed_row_shortfall(seed_output: str) -> list[str]:
    """Names of tables that planned > 0 rows but inserted 0.

    Parses both the `❌ SEED MISMATCH: <table> planned N inserted 0` markers and
    the per-table `seeded 0/N <table>` lines emitted by `seed.ts`. Pure output
    parse — no DB query. De-duplicated, order-preserving.
    """
    shortfalls: list[str] = []
    for line in seed_output.splitlines():
        for rx in (_MISMATCH_RE, _SEEDED_RE):
            m = rx.search(line)
            if not m:
                continue
            planned = int(m.group("planned"))
            inserted = int(m.group("inserted"))
            table = m.group("table").strip().strip(".,;:")
            if planned > 0 and inserted == 0 and table not in shortfalls:
                shortfalls.append(table)
            break
    return shortfalls


def parse_seed_output(returncode: int, output: str, timed_out: bool = False) -> dict:
    """Classify a seed-smoke run's result from its exit code + captured output.

    Success requires a clean exit, the `SEEDED_OK` sentinel, no error markers,
    AND no row-shortfall (a domain table that planned rows but landed zero).
    Pure function → unit-testable without Docker.
    """
    errors = _scan_errors(output)
    row_shortfall = detect_seed_row_shortfall(output)
    seeded = _SENTINEL in output
    ok = (
        (returncode == 0)
        and seeded
        and not errors
        and not row_shortfall
        and not timed_out
    )
    tail = "\n".join(output.splitlines()[-25:])
    return {
        "skipped": False,
        "ok": ok,
        "returncode": returncode,
        "seeded": seeded,
        "timed_out": timed_out,
        "errors": errors,
        "row_shortfall": row_shortfall,
        "output_tail": tail,
    }


def _precheck(output_dir: str) -> dict | None:
    """Return a `skipped` dict if the smoke run should not run, else None."""
    if not is_enabled():
        return {"skipped": True, "ok": None, "reason": f"{FLAG_ENV} not set"}
    start = os.path.join(str(output_dir), "start.sh")
    if not os.path.isfile(start):
        return {"skipped": True, "ok": None, "reason": "start.sh missing"}
    return None


def run_seed_smoke(output_dir: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Synchronously run `start.sh --seed-only` when enabled; classify the result.

    Returns a `skipped` dict when the flag is off or `start.sh` is missing (no
    Docker touched). Never raises.
    """
    pre = _precheck(output_dir)
    if pre is not None:
        return pre
    try:
        proc = subprocess.run(
            ["bash", "start.sh", "--seed-only"],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return parse_seed_output(proc.returncode, output)
    except subprocess.TimeoutExpired as e:  # noqa: BLE001
        out = (e.stdout or "") + "\n" + (e.stderr or "") if (e.stdout or e.stderr) else ""
        out = out if isinstance(out, str) else out.decode("utf-8", "replace")
        return parse_seed_output(-1, out, timed_out=True)
    except Exception as e:  # noqa: BLE001 — never crash generation on the gate
        logger.warning("seed_smoke: run failed to launch: %s", e)
        return {"skipped": True, "ok": None, "reason": f"launch error: {e}"}


async def run_seed_smoke_async(output_dir: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Async variant for the generation pipeline (non-blocking event loop).

    Same contract as `run_seed_smoke`; runs `start.sh --seed-only` via
    asyncio.create_subprocess_exec with a timeout. Never raises.
    """
    import asyncio

    pre = _precheck(output_dir)
    if pre is not None:
        return pre
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", "start.sh", "--seed-only",
            cwd=str(output_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return parse_seed_output(-1, "", timed_out=True)
        output = stdout.decode("utf-8", "replace") if stdout else ""
        return parse_seed_output(proc.returncode if proc.returncode is not None else -1, output)
    except Exception as e:  # noqa: BLE001 — never crash generation on the gate
        logger.warning("seed_smoke: async run failed to launch: %s", e)
        return {"skipped": True, "ok": None, "reason": f"launch error: {e}"}


def summarize(result: dict) -> str:
    """One-line human summary for an SSE/log line."""
    if result.get("skipped"):
        return f"seed-smoke SKIPPED ({result.get('reason', 'disabled')})"
    if result.get("ok"):
        return "seed-smoke PASS — DB migrated + seeded cleanly"
    bits = [f"rc={result.get('returncode')}"]
    if result.get("timed_out"):
        bits.append("TIMEOUT")
    if not result.get("seeded"):
        bits.append("no SEEDED_OK sentinel")
    errs = result.get("errors") or []
    if errs:
        bits.append(f"{len(errs)} error line(s): {errs[0][:160]}")
    shortfall = result.get("row_shortfall") or []
    if shortfall:
        bits.append(f"{len(shortfall)} table(s) planned rows but landed zero: "
                    f"{', '.join(shortfall[:8])}")
    return "seed-smoke FAIL — " + "; ".join(bits)
