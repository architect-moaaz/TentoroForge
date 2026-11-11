"""Live tracking (2026-11-06): a customer follows a driver's dot on a map while a
job runs. The page agent is told it exists and how to use it, a page that
imports it gets the map library, and every built app carries the two routes and
the mailbox they share.

What this does NOT prove: that a model, given these words, writes the right
page. That needs a model call; this checks the words and the wiring are there."""
import json
from pathlib import Path

from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, SDK_PACKAGES, TECH_RULES, ensure_sdk_packages

BACKEND = Path(__file__).resolve().parents[2]
FOUNDATION = BACKEND / "templates" / "app-foundation"
RUNTIME = BACKEND / "templates" / "runtime"


def test_the_page_agent_is_told_what_tracking_is_and_when_it_may_show_a_pin():
    # The import list says the module exists; the design rules say when to use it.
    assert '"@/sdk/tracking"' in TECH_RULES
    for word in ("LIVE TRACKING", "LiveTrackingMap", "ShareLocation"):
        assert word in DESIGN_PRINCIPLES, word
    # The privacy rule stays: outside a running job a person is still never a pin.
    assert "PLACES ARE DISTANCES" in DESIGN_PRINCIPLES
    assert "never after it is delivered" in DESIGN_PRINCIPLES


def test_the_components_the_agent_is_told_about_exist():
    src = (FOUNDATION / "src/sdk/tracking.tsx").read_text(encoding="utf-8")
    for name in ("export function LiveTrackingMap", "export function ShareLocation", "export function useLiveTrip"):
        assert name in src, name


def test_a_page_importing_tracking_gets_the_map_library(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^19.0.0"}}))
    added = ensure_sdk_packages(tmp_path, 'import { LiveTrackingMap } from "@/sdk/tracking";\n')
    assert added == ["maplibre-gl"]
    assert SDK_PACKAGES["@/sdk/tracking"] == ("maplibre-gl",)


def test_every_built_app_carries_the_tracking_routes_and_their_mailbox():
    injector = (BACKEND / "services" / "runtime_injector.py").read_text(encoding="utf-8")
    assert '"tracking"]' in injector, "the mailbox directory is copied with the other runtime libraries"
    for tmpl in ("api-tracking-update", "api-tracking-stream"):
        assert tmpl in injector, tmpl
        assert (RUNTIME / tmpl / "route.ts").is_file(), tmpl
    assert (RUNTIME / "tracking" / "hub.ts").is_file()
    # Both routes import the mailbox from where the injector puts it.
    for tmpl in ("api-tracking-update", "api-tracking-stream"):
        assert '@/lib/tracking/hub' in (RUNTIME / tmpl / "route.ts").read_text(encoding="utf-8")


def _prompts() -> str:
    """The instructions the requirements and data-model steps are given."""
    return (BACKEND / "services" / "blueprint" / "executors.py").read_text(encoding="utf-8")


def test_the_requirements_step_notices_tracking_without_the_word_gps():
    src = _prompts()
    assert "LIVE TRACKING IS RARELY CALLED THAT" in src
    for phrase in ("see how far away my driver is", "an `area` ", "named \\\"Live tracking\\\"", "never after it is delivered"):
        assert phrase in src, phrase


def test_the_requirements_step_is_told_what_is_not_tracking():
    """A store locator or a status a staff member types follows no one's position."""
    src = _prompts()
    for phrase in ("store locator", "restaurants nearby", "out for delivery"):
        assert phrase in src, phrase


def test_the_data_model_gives_a_followed_job_one_record_and_keeps_the_position_out_of_it():
    src = _prompts()
    assert "LIVE TRACKING NEEDS A JOB TO FOLLOW" in src
    assert "Do NOT store the moving position" in src
    assert "`location` fields" in src


def test_smith_in_chat_plans_live_tracking_in_order_and_does_not_mistake_a_distance_for_it():
    from services.smith.loop import _PROMPT
    assert "LIVE TRACKING IS SEVERAL CHANGES, NOT ONE" in _PROMPT
    for phrase in ("`propose_plan`", "`LiveTrackingMap`", "`ShareLocation`", "never a second one",
                   "Never\nkeep the moving position in a record", "NOT tracking when they want a\ndistance"):
        assert phrase in _PROMPT.replace("\r\n", "\n"), phrase
    # the order: the record first, then the follower, then the person on the move
    body = _PROMPT[_PROMPT.index("LIVE TRACKING IS SEVERAL"):]
    assert body.index("(1) the job record") < body.index("(2) the follower") < body.index("(3) the screen of the person")


def test_both_routes_ask_who_may_before_anything_else_and_the_helpers_ship():
    for name in ("rules.ts", "access.ts"):
        assert (RUNTIME / "tracking" / name).is_file(), name
    update = (RUNTIME / "api-tracking-update" / "route.ts").read_text(encoding="utf-8")
    stream = (RUNTIME / "api-tracking-stream" / "route.ts").read_text(encoding="utf-8")
    for src in (update, stream):
        assert "jobFor" in src and "whoIs" in src and "tripKey" in src
    assert "mayShare" in update and "finished" in update, "only the person on the move, never after the job"
    # a finished job's stream says done and closes: `over` must be USED, not only computed
    assert "if (over)" in stream
    # the engine's own read rule decides who may follow
    assert "engine.findById" in (RUNTIME / "tracking" / "access.ts").read_text(encoding="utf-8")


def test_the_page_agent_names_the_record_kind_and_leaves_the_checks_to_the_server():
    assert 'entity="Order"' in DESIGN_PRINCIPLES
    assert "a screen never checks that itself" in DESIGN_PRINCIPLES
    sdk = (FOUNDATION / "src/sdk/tracking.tsx").read_text(encoding="utf-8")
    assert "entity" in sdk and "stream?entity=" in sdk and '"denied"' in sdk


def test_the_data_model_makes_the_person_on_the_move_nameable_and_the_end_recognisable():
    src = _prompts()
    for phrase in ("`driverId`", "`courierId`", "only the", "`delivered`", "let that person open it"):
        assert phrase in src, phrase
