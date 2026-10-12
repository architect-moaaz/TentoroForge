"""When a process runs is a thing Smith changes.

"Run the reminder every Monday at nine", "stop the nightly digest", "run it
now", "escalate approvals not done in two days to the manager": each is a
field of the Blueprint the clock reads (`trigger.cron`, `trigger.enabled`,
a human step's `dueIn`/`escalateTo`), set here, committed like every other
change, and projected into the running copy. The one that is not a change
— "run it now" — fires the schedule through the app's own tick and reports
what ran.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

VERBS = ("set_schedule", "pause_schedule", "resume_schedule", "set_deadline", "run_now")
HUMAN_STEPS = ("user_task", "approval", "assignment", "task_pool")

SCHEDULE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["cron", "timezone", "reading"],
    "properties": {
        "cron": {"type": "string", "description": "Five fields: minute hour day-of-month month day-of-week. Empty when the sentence is not a cadence the clock can keep."},
        "timezone": {"type": "string", "description": "An IANA zone, from the application's locale or the sentence."},
        "reading": {"type": "string", "description": "The cron said back in words, or why the sentence is not one."},
    },
}
SCHEDULE_SYSTEM = (
    "You turn a sentence about WHEN a process should run into a five-field cron expression and an "
    "IANA timezone. 'Every weekday at 9' is `0 9 * * 1-5`; 'every 15 minutes' is `*/15 * * * *`; "
    "'the first of each month' is `0 0 1 * *`. When the sentence is not a cadence a clock can keep "
    "('when it rains', 'whenever someone asks'), `cron` is an empty string and `reading` says why."
)
DEADLINE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["dueInMinutes", "escalateTo", "reading"],
    "properties": {
        "dueInMinutes": {"type": "integer", "description": "How long a person has, in minutes, 0 or more; 0 when the sentence names no time."},
        "escalateTo": {"type": "string", "description": "The role an overdue task goes to, by its exact name from the list; empty when the sentence names none."},
        "reading": {"type": "string"},
    },
}
DEADLINE_SYSTEM = (
    "You read a sentence about how long a person has to do a step of a process, and who it goes to "
    "when they do not. Answer in minutes and with the exact role name from the roles given. A role "
    "the sentence does not name is an empty string."
)


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or [])}


def _client(client: Any) -> Any:
    if client is not None:
        return client
    from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
    return AnthropicModel(model=DEFAULT_MODEL, effort="low")


def _ask(client: Any, system: str, user: str, schema: dict) -> dict:
    reply = client(system=system, user=user, schema=schema)
    body = json.loads(getattr(reply, "text", reply))
    return body.get("result", body) if isinstance(body, dict) else {}


def _find(svc: Any, ref: str) -> tuple[dict | None, str]:
    from services.smith.workflow_change import _names, find_workflow
    wf = find_workflow(svc.doc, ref)
    if wf is None:
        return None, f"I cannot tell which process {ref!r} means. The processes are: {_names(svc.doc)}."
    return wf, ""


def _reproject(svc: Any, output_dir: str) -> list[str]:
    from services.smith.workflow_change import _project_runtime
    app_root = Path(output_dir) / "app"
    return _project_runtime(svc, str(app_root)) if app_root.is_dir() else []


def _commit(svc: Any, before: Any, wf: dict, request: str, interpretation: str) -> None:
    svc.commit(user_request=request, smith_interpretation=interpretation, before=before,
               affected=[str(wf.get("id") or "")])


def set_schedule(svc: Any, output_dir: str, *, workflow: str, change: str, client: Any = None,
                 reasoning: Any = None) -> dict:
    wf, why = _find(svc, workflow)
    if wf is None:
        return _envelope(False, reason=why)
    from services.blueprint.cron_expr import is_valid_cron
    locale = str((svc.doc.get("product") or {}).get("locale") or "en")
    body = _ask(_client(client), SCHEDULE_SYSTEM,
                f"Process: {wf.get('name')}. Application locale: {locale}. Sentence: {change}", SCHEDULE_SCHEMA)
    cron = str(body.get("cron") or "").strip()
    reading = str(body.get("reading") or "").strip()
    if not is_valid_cron(cron):
        return _envelope(False, reason=(f"I could not read {change!r} as a time the clock can keep"
                                        + (f" ({reading})" if reading else "") + ". Say it as a cadence."),
                         options=["Every day at 09:00", "Every Monday at 09:00", "Every hour", "Every 15 minutes"])
    tz = str(body.get("timezone") or "").strip()
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:  # noqa: BLE001 — an unreadable zone: the clock runs in UTC
        tz = ""
    before = svc.snapshot()
    trigger = dict(wf.get("trigger") or {})
    trigger.update({"kind": "schedule", "cron": cron, "enabled": True, "detail": change})
    if tz:
        trigger["timezone"] = tz
    else:
        trigger.pop("timezone", None)
    wf["trigger"] = trigger
    _commit(svc, before, wf, change, f"{wf.get('name')} runs on the clock: {cron}" + (f" in {tz}" if tz else ""))
    tell(reasoning, f"{wf.get('name')} now runs {reading or cron}.", "step")
    return _envelope(True, diff=f"{wf.get('name')} now runs {reading or cron} (`{cron}`" + (f", {tz}" if tz else "") + ").",
                     paths=_reproject(svc, output_dir))


def _toggle(svc: Any, output_dir: str, *, workflow: str, enabled: bool, reasoning: Any = None) -> dict:
    wf, why = _find(svc, workflow)
    if wf is None:
        return _envelope(False, reason=why)
    if str((wf.get("trigger") or {}).get("kind") or "") != "schedule":
        return _envelope(False, reason=f"{wf.get('name')} is not run by the clock, so there is nothing to "
                                       f"{'resume' if enabled else 'pause'}. Say when it should run and I will set a schedule.")
    if bool((wf.get("trigger") or {}).get("enabled", True)) == enabled:
        return _envelope(True, diff=f"{wf.get('name')} is already {'running' if enabled else 'paused'}.")
    before = svc.snapshot()
    wf["trigger"] = {**(wf.get("trigger") or {}), "enabled": enabled}
    word = "resumed" if enabled else "paused"
    _commit(svc, before, wf, f"{word} {wf.get('name')}", f"{wf.get('name')} {word}")
    tell(reasoning, f"{wf.get('name')} {word}.", "step")
    return _envelope(True, diff=f"{wf.get('name')} is {word}; " + ("the clock runs it again." if enabled else "the clock leaves it alone until you resume it."),
                     paths=_reproject(svc, output_dir))


def pause_schedule(svc: Any, output_dir: str, *, workflow: str, reasoning: Any = None, **_: Any) -> dict:
    return _toggle(svc, output_dir, workflow=workflow, enabled=False, reasoning=reasoning)


def resume_schedule(svc: Any, output_dir: str, *, workflow: str, reasoning: Any = None, **_: Any) -> dict:
    return _toggle(svc, output_dir, workflow=workflow, enabled=True, reasoning=reasoning)


def set_deadline(svc: Any, output_dir: str, *, workflow: str, change: str, client: Any = None,
                 reasoning: Any = None) -> dict:
    wf, why = _find(svc, workflow)
    if wf is None:
        return _envelope(False, reason=why)
    human = [s for s in wf.get("steps") or [] if isinstance(s, dict) and str(s.get("type") or "") in HUMAN_STEPS]
    if not human:
        return _envelope(False, reason=f"{wf.get('name')} has no step a person does, so there is no deadline to set.")
    by_name = {str(r.get("name")): str(r.get("id")) for r in svc.doc.get("roles") or []
               if isinstance(r, dict) and r.get("name") and r.get("id")}
    roles = list(by_name)
    body = _ask(_client(client), DEADLINE_SYSTEM,
                f"Process: {wf.get('name')}. Roles: {', '.join(roles) or '(none)'}. Sentence: {change}", DEADLINE_SCHEMA)
    minutes = int(body.get("dueInMinutes") or 0)
    to = str(body.get("escalateTo") or "").strip()
    if minutes <= 0:
        return _envelope(False, reason=f"I could not read how long people have from {change!r}. Say it as a time: "
                                       "'within 2 days', 'by the next morning', '4 hours'.")
    if to and to not in by_name:
        return _envelope(False, reason=f"{to!r} is not a role of this application. The roles are: {', '.join(roles)}.",
                         options=roles[:4])
    before = svc.snapshot()
    for s in human:
        cfg = dict(s.get("config") or {})
        cfg["dueIn"] = minutes
        if to:
            # THE ROLE'S ID, as the Blueprint names roles; the projection
            # writes the name the runtime compares.
            cfg["escalateTo"] = by_name[to]
        s["config"] = cfg
    _commit(svc, before, wf, change, f"{wf.get('name')}: a person has {minutes} minutes" + (f", then {to}" if to else ""))
    tell(reasoning, f"Deadline set on {wf.get('name')}.", "step")
    return _envelope(True, diff=f"{wf.get('name')}: people now have {minutes} minutes for {', '.join(str(s.get('key') or s.get('name') or 'the step') for s in human)}"
                                + (f"; an overdue one goes to {to}." if to else "."),
                     paths=_reproject(svc, output_dir))


def run_now(svc: Any, output_dir: str, *, workflow: str, reasoning: Any = None, **_: Any) -> dict:
    wf, why = _find(svc, workflow)
    if wf is None:
        return _envelope(False, reason=why)
    if str((wf.get("trigger") or {}).get("kind") or "") != "schedule":
        return _envelope(False, reason=f"{wf.get('name')} is not run by the clock; its button runs it. "
                                       "Say when it should run and I will set a schedule.")
    from services.blueprint.clock_check import slug_of, tick
    from services.blueprint.page_review import _query
    from services.smith import trials
    bench = trials.Bench(output_dir)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            return _envelope(False, reason=f"I could not start a copy of the app to run it: {exc}")
        status, body = tick(app, Path(output_dir) / "app", workflow=str(wf.get("id")), force="1")
        if status != 200:
            return _envelope(False, reason=f"the app's tick answered {status}; nothing ran.")
        forced = body.get("forced") if isinstance(body.get("forced"), dict) else {}
        if not forced.get("fired"):
            return _envelope(False, reason=f"the clock could not start {wf.get('name')}: {forced.get('reason') or 'no answer'}")
        rows = _query(app, f"select node_label, status, coalesce(error, '') from workflow_execution_log "
                           f"where workflow_id = '{slug_of(wf)}' order by created_at desc limit 8")
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    steps = [f"{r[0]}: {r[1]}" + (f" — {r[2][:120]}" if len(r) > 2 and r[2] else "") for r in reversed(rows) if r]
    tell(reasoning, f"Ran {wf.get('name')} now.", "step")
    return _envelope(True, diff=f"Ran {wf.get('name')} now on a copy of the data" + (": " + "; ".join(steps) if steps else "; nothing was logged") + ".")


def run(output_dir: str, verb: str, *, workflow: str, change: str = "", reasoning: Any = None,
        client: Any = None) -> dict:
    """One of the schedule verbs, as the loop calls a seam."""
    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not a schedule verb: {verb}")
    svc = BlueprintService.load(output_dir=output_dir)
    fn = {"set_schedule": set_schedule, "pause_schedule": pause_schedule, "resume_schedule": resume_schedule,
          "set_deadline": set_deadline, "run_now": run_now}[verb]
    try:
        return fn(svc, output_dir, workflow=workflow, change=change, client=client, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001 — the seam answers, never raises into the loop
        logger.warning("[schedule-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "run", "set_schedule", "pause_schedule", "resume_schedule", "set_deadline", "run_now"]
