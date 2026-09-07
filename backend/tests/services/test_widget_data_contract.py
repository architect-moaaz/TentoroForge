"""A data-bound widget must be bound to data, in the shape it asked for.

Two live symptoms on opmk18qr /dashboard, one cause repeated:

  "Team Coverage Health" reads 0%. Its Gauge props are
  {min, max, unit, showValue, label} — there is no `value` and no binding.
  It was never wired to anything; 0 is what a Gauge draws when asked to draw
  nothing, and it reads as a real measurement of zero coverage.

  "Recent Activity" reads "Someone" ten times. ActivityFeed's contract is
  {actor:{name}, action, target, timestamp}; it is bound to Notification,
  whose columns are {recipientName, type, message, createdAt}. Not one field
  lines up, so every row falls through to the component's placeholder.

Same shape as the delta and the percent bugs: two components each holding a
plausible half of a contract, with nothing checking they agree.
"""
from services.widget_data_contract import (
    feed_field_map, has_value_binding, reconcile_widget_data,
)

NOTIFICATION_COLS = ["id", "recipientId", "recipientName", "type", "message",
                     "referenceId", "isRead", "createdAt", "updatedAt"]


class TestMappingEntityColumnsOntoTheFeedContract:
    def test_it_finds_the_person_column_for_actor(self):
        assert feed_field_map(NOTIFICATION_COLS)["actor"] == "recipientName"

    def test_it_finds_the_time_column_for_timestamp(self):
        assert feed_field_map(NOTIFICATION_COLS)["timestamp"] == "createdAt"

    def test_it_uses_the_kind_column_as_the_action(self):
        assert feed_field_map(NOTIFICATION_COLS)["action"] == "type"

    def test_it_uses_the_prose_column_as_the_target(self):
        assert feed_field_map(NOTIFICATION_COLS)["target"] == "message"

    def test_it_prefers_an_explicit_name_column_over_a_recipient_one(self):
        m = feed_field_map(["id", "name", "recipientName", "createdAt"])
        assert m["actor"] == "name"

    def test_it_omits_what_it_cannot_find_rather_than_guessing(self):
        m = feed_field_map(["id", "blob"])
        assert "actor" not in m and "timestamp" not in m

    def test_it_never_maps_an_id_column_to_a_human_name(self):
        m = feed_field_map(["id", "recipientId", "createdAt"])
        assert m.get("actor") != "recipientId"


class TestSpottingAWidgetWiredToNothing:
    def test_a_gauge_with_no_value_is_unbound(self):
        assert has_value_binding({"type": "Gauge", "props": {
            "min": 0, "max": 100, "unit": "%", "label": "Coverage"}}) is False

    def test_a_gauge_with_a_binding_is_bound(self):
        assert has_value_binding({"type": "Gauge", "props": {
            "value": "{{coverage.value}}"}}) is True

    def test_a_literal_number_counts_as_bound(self):
        # An author who wrote 72 meant 72.
        assert has_value_binding({"type": "Gauge", "props": {"value": 72}}) is True

    def test_a_zero_the_author_wrote_counts_as_bound(self):
        assert has_value_binding({"type": "Gauge", "props": {"value": 0}}) is True


class TestReconcilingAPage:
    def _page(self):
        return {
            "root": {"children": [
                {"type": "Card", "props": {"title": "Team Coverage Health"},
                 "children": [{"type": "Gauge", "props": {
                     "min": 0, "max": 100, "unit": "%", "label": "Coverage"}}]},
                {"type": "Card", "props": {"title": "Recent Activity"},
                 "children": [{"type": "ActivityFeed", "props": {
                     "entries": "{{notifications}}"}}]},
            ]},
            "dataSources": [
                {"name": "notifications", "entity": "Notification", "op": "list"},
            ],
        }

    def _registry(self):
        return {"entities": {"Notification": {
            "columns": [{"name": c} for c in NOTIFICATION_COLS]}}}

    def test_the_feed_gets_a_field_map_from_the_real_columns(self):
        page = self._page()
        reconcile_widget_data(page, self._registry())
        feed = page["root"]["children"][1]["children"][0]
        assert feed["props"]["fields"]["actor"] == "recipientName"

    def test_the_unbound_gauge_stops_claiming_a_number(self):
        page = self._page()
        reconcile_widget_data(page, self._registry())
        card = page["root"]["children"][0]
        assert "Gauge" not in str(card), "a gauge wired to nothing must not draw 0"
        assert "EmptyState" in str(card)

    def test_it_says_what_it_did(self):
        page = self._page()
        rep = reconcile_widget_data(page, self._registry())
        assert rep["changed"] == 2
        assert any("Coverage" in n or "Gauge" in n for n in rep["notes"])

    def test_it_is_idempotent(self):
        page = self._page()
        reg = self._registry()
        reconcile_widget_data(page, reg)
        assert reconcile_widget_data(page, reg)["changed"] == 0

    def test_a_feed_whose_entity_it_cannot_resolve_is_left_alone(self):
        page = self._page()
        rep = reconcile_widget_data(page, {"entities": {}})
        feed = page["root"]["children"][1]["children"][0]
        assert "fields" not in feed["props"]


class TestReadingColumnsFromTheAppItself:
    """registry.json is not always there.

    opmk18qr has no contracts/registry.json and its plan.json lists entity
    NAMES only, so the field map had nothing to derive from and the feed kept
    saying "Someone". The generated app's Drizzle schema is the one place the
    real column names always exist, because the database is built from it.
    """

    def _write(self, tmp_path):
        d = tmp_path / "src" / "db" / "schema"
        d.mkdir(parents=True)
        (d / "notifications.ts").write_text('''
import { pgTable, uuid, text, boolean, timestamp } from "drizzle-orm/pg-core";
export const notifications = pgTable("notifications", {
  id: uuid("id").primaryKey(),
  recipientId: uuid("recipient_id"),
  recipientName: text("recipient_name"),
  type: text("type"),
  message: text("message"),
  isRead: boolean("is_read"),
  createdAt: timestamp("created_at"),
});
''', encoding="utf-8")
        return tmp_path

    def test_it_reads_the_real_columns(self, tmp_path):
        from services.widget_data_contract import entity_columns_from_app
        reg = entity_columns_from_app(str(self._write(tmp_path)))
        cols = [c["name"] for c in reg["entities"]["Notification"]["columns"]]
        assert "recipientName" in cols and "createdAt" in cols

    def test_the_entity_name_matches_what_a_dataSource_declares(self, tmp_path):
        # dataSources say entity: "Notification" (singular, capitalised).
        from services.widget_data_contract import entity_columns_from_app
        reg = entity_columns_from_app(str(self._write(tmp_path)))
        assert "Notification" in reg["entities"]

    def test_a_missing_schema_directory_is_not_an_error(self, tmp_path):
        from services.widget_data_contract import entity_columns_from_app
        assert entity_columns_from_app(str(tmp_path)) == {"entities": {}}

    def test_the_map_derived_this_way_fixes_the_live_feed(self, tmp_path):
        from services.widget_data_contract import (
            entity_columns_from_app, reconcile_widget_data)
        reg = entity_columns_from_app(str(self._write(tmp_path)))
        page = {
            "root": {"children": [{"type": "ActivityFeed",
                                   "props": {"entries": "{{notifications}}"}}]},
            "dataSources": [{"name": "notifications", "entity": "Notification"}],
        }
        reconcile_widget_data(page, reg)
        fields = page["root"]["children"][0]["props"]["fields"]
        assert fields["actor"] == "recipientName"
        assert fields["timestamp"] == "createdAt"
