from agents.planner import PLANNER_SYSTEM_PROMPT as P


def test_planner_demandates_crud_for_every_entity():
    low = P.lower()
    # The old blanket mandate must be gone.
    assert "every entity needs: list page" not in low
    # Primary/supporting classification must be present.
    assert "primary" in low and "supporting" in low
    # Explicit anti-default: don't make full CRUD screens for every table.
    assert "every table" in low


def test_planner_still_requires_primary_entity_journeys():
    low = P.lower()
    # Reachability is still guaranteed for the core objects.
    assert "primary entity" in low and "user_journey" in low
