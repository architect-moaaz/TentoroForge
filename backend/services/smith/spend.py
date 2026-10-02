"""What this application has cost to run — and, said plainly, what it is not.

The owner's phrasebook ends its list of dead ends with "how much has this cost
me?", against the note *no cost or usage visibility anywhere in the
conversation*. Nothing was ever missing except the way to ask: every model call
the pipeline makes has been written to a ledger for as long as there has been a
pipeline (:mod:`services.build_usage`), with the project, the agent, the model,
the tokens and a dollar figure on every row. This verb reads it back.

THE NUMBER IS NOT A PRICE, AND SAYING SO IS THE FEATURE. There is no billing
anywhere in this platform — no plan, no meter, no invoice, nothing that turns a
build into an amount somebody owes. What the ledger holds is what the model
provider charged the platform to run the calls, mostly worked out from token
counts at published list prices. Handing that to an owner under the word "cost"
without the sentence that says whose cost it is would be inventing a bill, and
an invented bill is a worse answer than the dead end it replaces.

THREE THINGS ARE REPORTED SEPARATELY BECAUSE THEY ARE DIFFERENT FACTS:

  * **measured** — the model provider reported the cost of that call.
  * **estimated** — we priced the tokens ourselves. Real arithmetic over real
    token counts, still an estimate, and named as one.
  * **unpriced** — a model :func:`build_usage.is_priced` holds no price for.
    Its tokens are counted and its dollars are withheld. Note that the ledger
    row for such a call carries an ``est_cost_usd`` anyway — `estimate_cost_usd`
    falls back to a sonnet-class price for an unknown model — so the figure is
    on disk and must be *dropped here*, not trusted.

BUILD VERSUS CHANGES. Which of the two a call belongs to is a fact the code
knows when it starts a run, so it is recorded then, as ``phase`` on the row
(see :class:`executors.RunUsage`). It is deliberately not reconstructed here by
matching timestamps against run boundaries: runs overlap, a fan-out spans
minutes, and a guess about money reads exactly like a fact. Rows written before
the phase was recorded carry none, and are reported as unsplit — in the total,
out of the split, and said out loud.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: How many stages the breakdown names before it stops being a breakdown.
TOP_STAGES = 5


def _application(output_dir: str | Path) -> tuple[str, str]:
    """``(project id, application name)`` for this output directory.

    The id is what the ledger's rows are tagged with — ``application.id``,
    which is also the directory's name. Falling back to the directory name
    when there is no Blueprint is not a guess: the id IS the directory name,
    and a project whose document has gone may still have spend recorded.
    """
    directory = Path(output_dir).name
    current = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        import json
        app = (json.loads(current.read_text("utf-8")).get("application") or {})
        return (str(app.get("id") or directory),
                str(app.get("name") or "").strip() or directory)
    except (OSError, ValueError, AttributeError):
        return directory, directory


def _stage(agent: str) -> str:
    """The node a row belongs to — ``page_layouts:a2ui_pages:compose`` is the
    page composer, ``observer:pages`` is the observer watching it."""
    return str(agent or "").split(":")[0] or "unknown"


def report(output_dir: str | Path) -> dict[str, Any]:
    """Everything the ledger knows about this application's spend.

    Every dollar figure in here is one the code can defend: an unpriced model
    contributes tokens and nothing else, and the split between building and
    changing is read off the rows rather than inferred.
    """
    from services.build_usage import is_priced, read_ledger

    project, name = _application(output_dir)
    rows = [r for r in read_ledger() if str(r.get("project") or "") == project]

    out: dict[str, Any] = {
        "project": project, "name": name, "events": len(rows),
        "build": {"cost_usd": 0.0, "events": 0},
        "change": {"cost_usd": 0.0, "events": 0},
        "unsplit": {"cost_usd": 0.0, "events": 0},
        "total_usd": 0.0, "measured_usd": 0.0, "estimated_usd": 0.0,
        "input_tokens": 0, "output_tokens": 0,
        "unpriced": {"models": [], "tokens": 0, "events": 0},
        "by_stage": [], "first_ts": 0.0, "last_ts": 0.0,
    }
    if not rows:
        return out

    stages: dict[str, float] = {}
    unpriced_models: set[str] = set()
    for row in rows:
        inp = int(row.get("input_tokens") or 0)
        outp = int(row.get("output_tokens") or 0)
        out["input_tokens"] += inp
        out["output_tokens"] += outp
        ts = float(row.get("ts") or 0.0)
        out["first_ts"] = min(out["first_ts"] or ts, ts)
        out["last_ts"] = max(out["last_ts"], ts)

        if not is_priced(row.get("model")):
            # The row HAS a dollar figure — `estimate_cost_usd` prices an
            # unknown model as sonnet-class rather than refusing. Using it
            # would put a number we made up into a total presented as spend.
            out["unpriced"]["events"] += 1
            out["unpriced"]["tokens"] += inp + outp
            unpriced_models.add(str(row.get("model") or "unknown"))
            continue

        sdk = float(row.get("sdk_cost_usd") or 0.0)
        cost = sdk if sdk > 0 else float(row.get("est_cost_usd") or 0.0)
        if sdk > 0:
            out["measured_usd"] += cost
        else:
            out["estimated_usd"] += cost
        out["total_usd"] += cost

        phase = str(row.get("phase") or "")
        side = out["build"] if phase == "build" else \
            out["change"] if phase == "change" else out["unsplit"]
        side["cost_usd"] += cost
        side["events"] += 1
        stages[_stage(row.get("agent"))] = stages.get(_stage(row.get("agent")), 0.0) + cost

    for key in ("total_usd", "measured_usd", "estimated_usd"):
        out[key] = round(out[key], 4)
    for side in ("build", "change", "unsplit"):
        out[side]["cost_usd"] = round(out[side]["cost_usd"], 4)
    out["unpriced"]["models"] = sorted(unpriced_models)
    out["by_stage"] = [{"stage": s, "cost_usd": round(c, 4)}
                       for s, c in sorted(stages.items(),
                                          key=lambda kv: -kv[1])][:TOP_STAGES]
    return out


def _money(amount: float) -> str:
    """A dollar figure at the precision it is actually known to.

    Cents for anything a person would recognise as an amount; four places
    below that, because "$0.00" for a real 4/10ths of a cent reads as free.
    """
    return f"${amount:,.2f}" if amount >= 0.01 else f"${amount:.4f}"


def _provenance(out: dict[str, Any]) -> str:
    """The sentence that says what kind of number the total is."""
    measured, estimated = out["measured_usd"], out["estimated_usd"]
    if measured and estimated:
        return (f"{_money(measured)} of that is what the model provider "
                f"reported; the other {_money(estimated)} is worked out here "
                "from the tokens each call used, at published list prices.")
    if measured:
        return "That is what the model provider reported for those calls."
    return ("That is worked out from the tokens each call used, at the model "
            "provider's published list prices — real arithmetic over real "
            "token counts, and still an estimate.")


#: The sentence this whole verb exists to be allowed to say. A cost figure
#: handed to an owner without it is a bill nobody issued.
NOT_A_BILL = (
    "**This is not what you owe.** It is what the AI models cost to run — the "
    "platform's own cost of making this application. Forge does not charge you "
    "for a build and holds no price for one, so there is no bill for me to read "
    "you, and I will not turn this figure into one."
)


def summary_of(out: dict[str, Any]) -> str:
    """The answer, as markdown for the chat bubble."""
    name = out["name"]
    if not out["events"]:
        return (f"I have nothing recorded against **{name}**. No model call has "
                "been written to the usage ledger for this application — so "
                "rather than show you a zero that looks like a statement, I "
                "would rather say plainly that I cannot see what it cost.")

    if not out["total_usd"] and out["unpriced"]["events"]:
        # Nothing here can be mistaken for a bill, because there is no figure
        # at all — so the answer is the work, and why there is no money on it.
        return "\n".join([
            f"Every model call recorded against **{name}** ran on "
            + ", ".join(f"`{m}`" for m in out["unpriced"]["models"])
            + ", which I hold no price for — so I can tell you the work but "
              "not the money.",
            "",
            f"{out['input_tokens']:,} tokens read and "
            f"{out['output_tokens']:,} written, over "
            f"{out['events']:,} call(s). Putting a dollar figure on those "
            "would mean inventing a price, and I would rather leave the gap "
            "where you can see it."])

    # THE CALLS THE FIGURE IS MADE OF, not every call recorded — an unpriced
    # one is in `events` and contributes no dollars, and a count that mixes
    # the two makes the sentence quietly wrong.
    priced = out["events"] - out["unpriced"]["events"]
    lines = [f"**{name}** has cost {_money(out['total_usd'])} to run so far, "
             f"across {priced:,} model call(s)."]

    build, change, unsplit = out["build"], out["change"], out["unsplit"]
    if build["events"] or change["events"]:
        lines += ["",
                  (f"- Building it — **{_money(build['cost_usd'])}** over "
                   f"{build['events']:,} call(s)" if build["events"]
                   else "- Building it — nothing recorded"),
                  (f"- Changes since — **{_money(change['cost_usd'])}** over "
                   f"{change['events']:,} call(s)" if change["events"]
                   else "- Changes since — nothing yet")]
        if unsplit["events"]:
            lines += ["", (f"A further {_money(unsplit['cost_usd'])} was "
                           "recorded before a call said which of the two it "
                           "was, so it is in the total above and not in the "
                           "split.")]
    elif unsplit["events"]:
        lines += ["", ("I cannot split that between building it and the changes "
                       "since: these calls were recorded before each one said "
                       "which it was. From here on they are told apart.")]

    if out["by_stage"]:
        lines += ["", "Where it went: " + " · ".join(
            f"{s['stage']} {_money(s['cost_usd'])}" for s in out["by_stage"]) + "."]

    # ASKED FOR IN TOKENS AS OFTEN AS IN DOLLARS — "how many tokens has this
    # used" is the same question, and the tokens are the part that is measured
    # rather than estimated, so they are said outright.
    lines += ["", f"{out['input_tokens']:,} tokens read and "
                  f"{out['output_tokens']:,} written."]

    if out["total_usd"]:
        lines += ["", _provenance(out)]
    lines += ["", NOT_A_BILL]

    unpriced = out["unpriced"]
    if unpriced["events"]:
        # "Another", not "of those" — the headline counted the priced calls,
        # so these are beside that count, not inside it.
        lines += ["", (f"Another {unpriced['events']:,} call(s) ran on "
                       + ", ".join(f"`{m}`" for m in unpriced["models"])
                       + f", which I hold no price for. Their "
                       f"{unpriced['tokens']:,} tokens are in the token count "
                       "above; "
                       "their dollars are in no total here, because I would "
                       "have to make them up.")]
    return "\n".join(lines).strip()


def run(output_dir: str | Path, *, reasoning: Any = None) -> dict[str, Any]:
    """One spend answer from an `output_dir` — the shape a tool handler needs.

    Reads and changes nothing, so unlike every other verb it has no failure
    that leaves the application half-done: the worst case is that it cannot
    see the ledger, and it says so.
    """
    from services.llm_client import tell

    try:
        out = report(output_dir)
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[smith] spend report failed")
        return {"applied": False, "edited_paths": [],
                "reason": f"I could not read the usage ledger ({type(exc).__name__}: {exc}), "
                          "so I have no figure for you rather than a guessed one."}
    tell(reasoning, f"Reading what {out['name']} has cost to run.", "step")
    return {"applied": True, "edited_paths": [], "reason": "",
            "diff_summary": summary_of(out), **out}


__all__ = ["NOT_A_BILL", "TOP_STAGES", "report", "run", "summary_of"]
