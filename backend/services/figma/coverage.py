"""Does the design the person connected cover what the application has to do?

Asked once, when a design has been connected and before anything is built from it, so a person
learns "this design has no screen for approving a request" while they can still draw one, rather
than from a finished application that is missing it.

WHY THIS IS A JUDGEMENT AND NOT A DIFF
--------------------------------------
`figma_intelligence` already turns frames into requirements, each citing its frame. The obvious
check is therefore "which of the brief's requirements has a Figma-cited twin?" It cannot work: a
requirement's identity is a hash of its normalised wording (`ids.prose_key`, "deliberately *not*
fuzzy"), so the same capability worded by the brief and again by the design agent is two ids, never
merged. Whether a frame covers a requirement is a question of meaning, so it is put once, to a model,
over what the extraction already keeps (`brief.brief_for`: each frame's name, size and labels).

The model reports; CODE decides. The verdict (`sufficient`) is computed here from the statuses,
never read off the model's opinion, and everything the model names is checked against what was
actually sent: a frame or requirement it invents is dropped, and a requirement it forgot is counted
as not covered rather than quietly passing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Statuses a requirement can have against the design.
COVERED, PARTIAL, MISSING, NOT_A_SCREEN = "covered", "partial", "missing", "not_a_screen"
STATUSES = (COVERED, PARTIAL, MISSING, NOT_A_SCREEN)

MAX_REQUIREMENTS = 80
MAX_FRAMES = 60

#: What the person is offered when the design falls short. Fixed text, because the chat recognises
#: the answer by it (as the designer question does).
UPDATE_AND_RECHECK = "Update my Figma and check again"
FILL_WITH_FORGE = "Let Forge design the missing screens"
ONLY_WHAT_I_DREW = "Build only what I drew"
OPTIONS = (UPDATE_AND_RECHECK, FILL_WITH_FORGE, ONLY_WHAT_I_DREW)

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["requirements", "unmatchedFrames", "missingScreens", "frameChanges"],
    "properties": {
        "requirements": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "status", "frames", "reason"],
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string", "enum": list(STATUSES)},
                "frames": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"}}}},
        "unmatchedFrames": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nodeId", "note"],
            "properties": {"nodeId": {"type": "string"}, "note": {"type": "string"}}}},
        "missingScreens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "why", "requirements"],
            "properties": {"name": {"type": "string"}, "why": {"type": "string"},
                           "requirements": {"type": "array", "items": {"type": "string"}}}}},
        "frameChanges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nodeId", "change", "requirements"],
            "properties": {"nodeId": {"type": "string"}, "change": {"type": "string"},
                           "requirements": {"type": "array", "items": {"type": "string"}}}}},
    },
}

SYSTEM = (
    "You check whether a design a person drew in Figma covers what an application has to do. You are "
    "given the application's requirements and the design's frames (each with its name, size and the "
    "visible text on it). For EVERY requirement, say:\n"
    "- `covered`: a frame shows the screen or control that satisfies it. Name the frame(s).\n"
    "- `partial`: a frame is clearly the right screen but lacks something the requirement needs "
    "(a filter, a field, a state). Name the frame and say what is missing.\n"
    "- `missing`: no frame shows it, and it needs a screen or control of its own.\n"
    "- `not_a_screen`: it is a rule, a permission, a notification, an integration or a quality "
    "(performance, security) that a drawing cannot show. It does not count against the design.\n\n"
    "A design is evidence of what the application DOES, not of everything it needs. Sign-in, empty "
    "states, error states and permission-denied screens are almost never drawn and are added by the "
    "builder: mark a requirement that is only that `not_a_screen`, never `missing`.\n\n"
    "Use ONLY the frame `nodeId`s and requirement `id`s you are given; never invent one. Judge by "
    "what a frame's name and text actually show, not by what such a screen usually contains. "
    "`unmatchedFrames` are frames that serve no requirement (say what they seem to be). "
    "`missingScreens` names each screen the design would need to cover the `missing` requirements, "
    "with the requirement ids that need it. `frameChanges` lists what an existing frame lacks for a "
    "`partial` requirement. Be specific and short."
)


class CoverageUnavailable(Exception):
    """The check could not be made (no design stored, no model answered). The message is safe to show."""


@dataclass
class Coverage:
    covered: list[dict] = field(default_factory=list)
    partial: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    not_a_screen: list[dict] = field(default_factory=list)
    unmatched_frames: list[dict] = field(default_factory=list)
    missing_screens: list[dict] = field(default_factory=list)
    frame_changes: list[dict] = field(default_factory=list)
    frames: int = 0

    @property
    def sufficient(self) -> bool:
        """Every requirement a drawing can show is shown, at least in part. Decided here."""
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {"sufficient": self.sufficient, "frames": self.frames, "covered": self.covered,
                "partial": self.partial, "missing": self.missing, "notAScreen": self.not_a_screen,
                "unmatchedFrames": self.unmatched_frames, "missingScreens": self.missing_screens,
                "frameChanges": self.frame_changes}


def requirements_of(doc: dict) -> list[dict]:
    """The live requirements, as the check sees them."""
    out = []
    for r in doc.get("requirements") or []:
        if not isinstance(r, dict) or not r.get("id") or r.get("status") == "DEPRECATED":
            continue
        text = str(r.get("description") or r.get("statement") or r.get("name") or "").strip()
        if text:
            out.append({"id": str(r["id"]), "description": text,
                        **({"priority": r["priority"]} if r.get("priority") else {})})
    return out[:MAX_REQUIREMENTS]


def frames_of(doc: dict, output_dir: Any) -> list[dict]:
    """Every connected Figma frame that looks like a screen, with its text — `brief_for`, once per source."""
    from services.figma.brief import brief_for

    out: list[dict] = []
    for source in doc.get("designSources") or []:
        sid = str((source or {}).get("id") or "")
        if not sid or str(source.get("provider") or "figma") != "figma":
            continue
        for screen in brief_for(doc, sid, output_dir).get("screens") or []:
            if isinstance(screen, dict) and screen.get("nodeId"):
                out.append({k: screen[k] for k in ("nodeId", "name", "size", "labels") if screen.get(k)})
    return out[:MAX_FRAMES]


def _prompt(reqs: list[dict], frames: list[dict]) -> str:
    return ("Requirements:\n```json\n" + json.dumps(reqs, indent=1) + "\n```\n\nDesign frames:\n```json\n"
            + json.dumps(frames, indent=1) + "\n```")


def _ids(values: Any, allowed: set[str]) -> list[str]:
    return [str(v) for v in values or [] if str(v) in allowed]


def interpret(reply: dict, reqs: list[dict], frames: list[dict]) -> Coverage:
    """The model's answer, held to what was sent. Pure, so it is tested without a model."""
    req_by_id = {r["id"]: r for r in reqs}
    frame_ids = {f["nodeId"]: f for f in frames}
    cov = Coverage(frames=len(frames))
    said: dict[str, dict] = {}
    for item in reply.get("requirements") or []:
        if isinstance(item, dict) and str(item.get("id")) in req_by_id and str(item.get("id")) not in said:
            said[str(item["id"])] = item
    for rid, req in req_by_id.items():
        item = said.get(rid)
        if item is None:
            # A requirement the model did not mention is not a requirement that passed.
            cov.missing.append({**req, "frames": [], "reason": "the check did not assess it"})
            continue
        status = item.get("status") if item.get("status") in STATUSES else MISSING
        row = {**req, "frames": _ids(item.get("frames"), set(frame_ids)),
               "reason": str(item.get("reason") or "").strip()}
        if status == COVERED and not row["frames"]:
            status = MISSING               # "covered" by no frame is not covered
            row["reason"] = row["reason"] or "no frame was named for it"
        {COVERED: cov.covered, PARTIAL: cov.partial, MISSING: cov.missing,
         NOT_A_SCREEN: cov.not_a_screen}[status].append(row)
    for u in reply.get("unmatchedFrames") or []:
        if isinstance(u, dict) and str(u.get("nodeId")) in frame_ids:
            f = frame_ids[str(u["nodeId"])]
            cov.unmatched_frames.append({"nodeId": f["nodeId"], "name": f.get("name", ""),
                                         "note": str(u.get("note") or "").strip()})
    for m in reply.get("missingScreens") or []:
        if isinstance(m, dict) and str(m.get("name") or "").strip():
            cov.missing_screens.append({"name": str(m["name"]).strip(), "why": str(m.get("why") or "").strip(),
                                        "requirements": _ids(m.get("requirements"), set(req_by_id))})
    for c in reply.get("frameChanges") or []:
        if isinstance(c, dict) and str(c.get("nodeId")) in frame_ids and str(c.get("change") or "").strip():
            cov.frame_changes.append({"nodeId": str(c["nodeId"]), "name": frame_ids[str(c["nodeId"])].get("name", ""),
                                      "change": str(c["change"]).strip(),
                                      "requirements": _ids(c.get("requirements"), set(req_by_id))})
    return cov


def check(doc: dict, output_dir: Any, client: Any) -> Coverage:
    """Judge the connected design against the requirements. Raises :class:`CoverageUnavailable`."""
    reqs = requirements_of(doc)
    if not reqs:
        raise CoverageUnavailable("The application has no requirements to check a design against yet.")
    frames = frames_of(doc, output_dir)
    if not frames:
        raise CoverageUnavailable("No screens were read from the connected Figma design.")
    try:
        reply = client(system=SYSTEM, user=_prompt(reqs, frames), schema=SCHEMA)
        body = json.loads(getattr(reply, "text", reply))
    except Exception as exc:  # noqa: BLE001 — the person is told, the build is not stopped by it
        logger.warning("[figma-coverage] %s: %s", type(exc).__name__, str(exc)[:200])
        raise CoverageUnavailable("I could not check the design against the requirements just now.") from exc
    if not isinstance(body, dict):
        raise CoverageUnavailable("The check came back in a form I could not read.")
    return interpret(body, reqs, frames)


def report(cov: Coverage) -> str:
    """What Smith says. Plain, specific, and the three ways forward when there are gaps."""
    n_req = len(cov.covered) + len(cov.partial) + len(cov.missing)
    head = (f"I read {cov.frames} screen{'s' if cov.frames != 1 else ''} from your design and checked "
            f"them against {n_req} requirement{'s' if n_req != 1 else ''} that need a screen.")
    if cov.sufficient:
        lines = [head, "", f"**Your design covers the application** ({len(cov.covered)} fully"
                 + (f", {len(cov.partial)} partly" if cov.partial else "") + ")."]
        if cov.partial or cov.frame_changes:
            lines += ["", "Worth tightening, but nothing blocks the build:"]
            lines += [f"- {c['name'] or c['nodeId']}: {c['change']}" for c in cov.frame_changes[:6]]
        lines += ["", "Sign-in, empty states and error screens are never in a design; I will add them."]
        return "\n".join(lines)
    lines = [head, "", f"**The design is missing {len(cov.missing)} thing{'s' if len(cov.missing) != 1 else ''} "
             "the application needs:**"]
    lines += [f"- {m['description']}" + (f" — {m['reason']}" if m.get("reason") else "") for m in cov.missing[:10]]
    if cov.missing_screens:
        lines += ["", "Screens that would cover them:"]
        lines += [f"- **{s['name']}**" + (f": {s['why']}" if s.get("why") else "") for s in cov.missing_screens[:8]]
    if cov.frame_changes:
        lines += ["", "And these frames lack something:"]
        lines += [f"- {c['name'] or c['nodeId']}: {c['change']}" for c in cov.frame_changes[:6]]
    if cov.unmatched_frames:
        lines += ["", "Frames that serve no requirement: "
                  + ", ".join(u["name"] or u["nodeId"] for u in cov.unmatched_frames[:6]) + "."]
    lines += ["", "How would you like to go on?",
              f"- **{UPDATE_AND_RECHECK}:** draw or change the screens above, then tell me and I will look again.",
              f"- **{FILL_WITH_FORGE}:** your frames are built as drawn; Forge designs the rest in the same style.",
              f"- **{ONLY_WHAT_I_DREW}:** the application is exactly the screens in your design."]
    return "\n".join(lines)
