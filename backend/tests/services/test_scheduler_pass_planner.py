"""Tests for Spec D Wave 2 — planner-authored `entity.schedulable_by`
precedence on scheduler_pass.detect_scheduler. Additive: the resource/
person word-list classifier stays intact as the fallback.
"""
from __future__ import annotations

from services.scheduler_pass import detect_scheduler


def _entities_with_item(item_kind: str = "Widget",
                        resource_kind: str = "Widget",
                        extra: dict | None = None) -> dict:
    """Build an ITEM/RESOURCE pair whose entity names are DELIBERATELY not
    in the built-in `_RESOURCE_WORDS` list so the legacy classifier fails
    without a planner hint.
    """
    ents = {
        f"{item_kind}Slot": {
            "fields": {
                "id":         {"type": "uuid"},
                "startAt":    {"type": "timestamp"},
                "endAt":      {"type": "timestamp"},
                f"{resource_kind.lower()}Id": {"type": "uuid"},
            }
        },
        resource_kind: {
            "fields": {
                "id":   {"type": "uuid"},
                "name": {"type": "text"},
            }
        },
    }
    if extra:
        ents.update(extra)
    return ents


class TestPlannerResourceWins:
    def test_planner_resource_pairs_with_item(self):
        # Legacy classifier would fail: 'Widget' isn't a bookable resource
        # word. Planner marks it schedulable_by='resource' → we pair it
        # with the WidgetSlot item that has date range + FK to Widget.
        ents = _entities_with_item("Widget", "Widget")
        ents["Widget"]["schedulable_by"] = "resource"
        m = detect_scheduler(ents)
        assert m is not None
        assert m["resourceEntity"] == "Widget"
        assert m["itemEntity"] == "WidgetSlot"
        assert m["itemResourceField"] == "widgetId"
        assert m.get("reason") == "planner:resource"


class TestPlannerOptOut:
    def test_planner_none_returns_none(self):
        # Even a schedulable-shaped domain (room + booking) is silenced
        # when the room entity carries schedulable_by='none'.
        ents = {
            "Booking": {
                "fields": {
                    "id":    {"type": "uuid"},
                    "start": {"type": "timestamp"},
                    "end":   {"type": "timestamp"},
                    "roomId": {"type": "uuid"},
                }
            },
            "Room": {
                "schedulable_by": "none",
                "fields": {
                    "id":   {"type": "uuid"},
                    "name": {"type": "text"},
                }
            },
        }
        assert detect_scheduler(ents) is None

    def test_planner_false_flag_returns_none(self):
        ents = {
            "Booking": {
                "fields": {
                    "start": {"type": "timestamp"},
                    "end":   {"type": "timestamp"},
                    "roomId": {"type": "uuid"},
                }
            },
            "Room": {
                "schedulable_by": False,
                "fields": {"id": {"type": "uuid"}, "name": {"type": "text"}},
            },
        }
        assert detect_scheduler(ents) is None


class TestLegacyPathPreserved:
    def test_no_planner_flag_uses_resource_word_list(self):
        # Room is in `_RESOURCE_WORDS`; legacy classifier picks it.
        ents = {
            "Booking": {
                "fields": {
                    "id":    {"type": "uuid"},
                    "start": {"type": "timestamp"},
                    "end":   {"type": "timestamp"},
                    "roomId": {"type": "uuid"},
                }
            },
            "Room": {
                "fields": {"id": {"type": "uuid"}, "name": {"type": "text"}},
            },
        }
        m = detect_scheduler(ents)
        assert m is not None
        assert m["resourceEntity"] == "Room"
        assert m["itemEntity"] == "Booking"

    def test_no_signal_returns_none(self):
        # No date range on any entity → legacy path finds nothing.
        ents = {"Widget": {"fields": {"id": {"type": "uuid"}, "name": {"type": "text"}}}}
        assert detect_scheduler(ents) is None


class TestFlagShapeTolerance:
    def test_unknown_flag_value_falls_through(self):
        # 'maybe' isn't a recognized planner value → fall through to
        # legacy path (which finds nothing here because Widget isn't a
        # bookable-resource word).
        ents = _entities_with_item("Widget", "Widget")
        ents["Widget"]["schedulable_by"] = "maybe"
        assert detect_scheduler(ents) is None

    def test_missing_flag_uses_legacy(self):
        ents = _entities_with_item("Widget", "Widget")
        # No planner flag anywhere → legacy path, no bookable-resource
        # word matches, returns None.
        assert detect_scheduler(ents) is None
