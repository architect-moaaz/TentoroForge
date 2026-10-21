"""A repair that had to reach into the platform's engine is a platform
fault, not the app's: the loop says so, records it, marks the red, and
does not work it again. Thirty reds were worked twice and fixed zero
times because every one was the engine's (pcn4owv7, 2026-10-14)."""
from __future__ import annotations

import json
from pathlib import Path

from services import incidents
from services.blueprint import fix_to_green as ftg
from services.blueprint import scorecard as sc
from tests.services.test_fixing_stops_when_nothing_turns_green import DOC, _Svc


def _wire(monkeypatch, svc, reds, answers):
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(lambda cls, output_dir: svc))
    monkeypatch.setattr("services.run_registry.turn_in_flight", lambda out: False)
    monkeypatch.setattr(ftg, "_check_everything", lambda svc_, *a, **k: [sc.write(svc_, c, green=0, red=items, untried=[]) for c, items in reds.items()])
    # Nothing turns green on its own: the check again keeps every red.
    monkeypatch.setattr(ftg, "_check_again", lambda svc_, *a, **k: None)
    asked = []

    def run_turn(pid, output_dir, ask, **k):
        asked.append(ask)
        return answers.pop(0) if answers else {"answer": "nothing", "edited_paths": []}
    return asked, run_turn


def test_a_platform_fault_is_said_recorded_marked_and_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr("services.project_paths.OUTPUT_ROOT", tmp_path, raising=False)
    out = tmp_path / "pcn4owv7"
    svc = _Svc(out, DOC)
    sc.seed_from_boot(svc)
    reds = {"pages": [sc.item("PAGE-002", "Transaction History", "it shows 'NaN'", "PAGE-002"),
                      sc.item("PAGE-003", "Calendar", "button errors", "PAGE-003")]}
    # The first repair edits the engine; the second edits the app and still fails.
    answers = [{"answer": "Changed the platform's `src/lib/data-engine.ts` for this app: Dates to strings.",
                "edited_paths": ["src/lib/data-engine.ts"]},
               {"answer": "Rewrote /calendar", "edited_paths": ["src/app/(dashboard)/calendar/view.tsx"]}]
    # The app's classifier: the engine's file is the platform's, a page file is the app's.
    monkeypatch.setattr("services.smith.file_edit.classify",
                        lambda doc, rel: {"kind": "platform"} if rel.startswith("src/lib/") else {"kind": "page"})
    asked, run_turn = _wire(monkeypatch, svc, reds, answers)
    said = []
    out_ = ftg.run_checks_to_green(svc, str(out), str(out / "app"), None,
                                   emit=lambda e, d: said.append(d.get("text", "")) if e == "message" else None,
                                   run_turn=run_turn, record=False)
    texts = "\n".join(said)
    assert "Transaction History — the fault is in the platform's engine (`src/lib/data-engine.ts`)" in texts
    # Marked on the card, and never asked for again.
    card = sc.read(svc.doc)
    reds_now = card["criteria"]["pages"]["red"]
    assert next(r for r in reds_now if r["id"] == "PAGE-002")["platform"] == "src/lib/data-engine.ts"
    assert not any("Transaction History" in a for a in asked[1:]), asked
    # Said in the closing as not the app's, and on the record for the cockpit.
    closing = said[-1]
    assert "Not the app's to fix (1): Transaction History (src/lib/data-engine.ts)" in closing
    assert "Still not right (1): Calendar" in closing
    rows = incidents.recent()
    assert rows and rows[0]["kind"] == "platform_fault" and rows[0]["app"] == "pcn4owv7" and rows[0]["path"] == "src/lib/data-engine.ts"
    assert out_["stopped"] in ("yield", "turns", "time", "tried")


def test_the_words_alone_name_a_platform_fault(tmp_path):
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(DOC))
    assert ftg.platform_fault(str(tmp_path), {"answer": "Took back the change to the platform's `src/lib/x.ts`.", "edited_paths": []}) == "src/lib/x.ts"
    assert ftg.platform_fault(str(tmp_path), {"answer": "Rewrote /calendar", "edited_paths": []}) is None
    assert ftg.platform_fault(str(tmp_path), None) is None
