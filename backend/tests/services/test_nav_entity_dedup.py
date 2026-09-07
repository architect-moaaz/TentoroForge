"""The menu must not offer the same destination twice, once in table-speak.

Live on opmk18qr the sidebar read:

    Approvals · Dashboard · employees · hr_admins · managers · My Balance ·
    Requests · Tasks · Team Calendar · Requests · Employees · Leave Types ·
    Holidays · Departments · Analytics

Three of those — ``employees`` /employees, ``managers`` /managers,
``hr_admins`` /hr-admins — are raw entity identifiers appended so that every
entity would be *reachable*. But ``/admin/employees`` already reached
Employees, under a proper label. Reachability was satisfied twice and the user
was shown the plumbing.

The nav merge deduped by ROUTE, so ``/employees`` and ``/admin/employees``
looked like different destinations. Entity coverage — not route equality — is
what the completeness rule actually meant, so that is what this checks.
"""
from services.nav_entity_dedup import (
    humanize_entity_label, is_raw_entity_label, reconcile_entity_pages,
    reconcile_nav_flow,
)


class TestSpottingTableSpeak:
    def test_snake_case_is_table_speak(self):
        assert is_raw_entity_label("hr_admins") is True

    def test_an_all_lowercase_plural_is_table_speak(self):
        assert is_raw_entity_label("employees") is True

    def test_a_written_label_is_not(self):
        for good in ("Employees", "My Balance", "Team Calendar", "Leave Types"):
            assert is_raw_entity_label(good) is False, good

    def test_a_single_capitalised_word_is_not(self):
        assert is_raw_entity_label("Requests") is False


class TestHumanising:
    def test_it_splits_and_titles(self):
        assert humanize_entity_label("employees") == "Employees"
        assert humanize_entity_label("leave_types") == "Leave Types"

    def test_it_keeps_known_initialisms_upper(self):
        assert humanize_entity_label("hr_admins") == "HR Admins"


class TestReconcilingThePlansPages:
    def _pages(self):
        return [
            {"name": "Employees", "route": "/admin/employees", "kind": "list"},
            {"name": "employees", "route": "/employees"},
            {"name": "managers", "route": "/managers"},
            {"name": "hr_admins", "route": "/hr-admins"},
        ]

    def test_it_drops_the_slug_page_an_admin_route_already_covers(self):
        pages = self._pages()
        report = reconcile_entity_pages(pages)
        routes = [p["route"] for p in pages]
        assert "/employees" not in routes
        assert "/admin/employees" in routes
        assert report["dropped"] == 1

    def test_it_keeps_a_slug_page_that_is_the_only_way_in(self):
        # No other page reaches managers — dropping it would strand the entity,
        # which is the very thing the completeness rule exists to prevent.
        pages = self._pages()
        reconcile_entity_pages(pages)
        assert "/managers" in [p["route"] for p in pages]

    def test_it_humanises_the_labels_it_keeps(self):
        pages = self._pages()
        reconcile_entity_pages(pages)
        kept = {p["route"]: p["name"] for p in pages}
        assert kept["/managers"] == "Managers"
        assert kept["/hr-admins"] == "HR Admins"

    def test_it_never_touches_a_properly_authored_page(self):
        pages = self._pages()
        reconcile_entity_pages(pages)
        admin = [p for p in pages if p["route"] == "/admin/employees"][0]
        assert admin["name"] == "Employees" and admin["kind"] == "list"

    def test_it_is_idempotent(self):
        pages = self._pages()
        reconcile_entity_pages(pages)
        assert reconcile_entity_pages(pages) == {"dropped": 0, "renamed": 0, "notes": []}

    def test_a_detail_route_does_not_count_as_covering_the_entity(self):
        # /employees/[id] reaches one employee, not the list — it must not
        # justify dropping the only list page.
        pages = [
            {"name": "Employee", "route": "/employees/[id]", "kind": "detail"},
            {"name": "employees", "route": "/employees"},
        ]
        reconcile_entity_pages(pages)
        assert "/employees" in [p["route"] for p in pages]

    def test_it_reports_what_it_did(self):
        pages = self._pages()
        report = reconcile_entity_pages(pages)
        assert "/employees" in str(report["notes"])
        assert "/admin/employees" in str(report["notes"])


class TestTheNavFlowBackstop:
    def _write(self, tmp_path, pages):
        import json
        p = tmp_path / "nav-flow.json"
        p.write_text(json.dumps({"pages": pages}), encoding="utf-8")
        return p

    def test_a_duplicate_leaves_the_menu_but_keeps_its_route(self, tmp_path):
        import json
        p = self._write(tmp_path, [
            {"title": "Employees", "route": "/admin/employees", "shell": True},
            {"title": "employees", "route": "/employees", "shell": True},
        ])
        rep = reconcile_nav_flow(str(p))
        pages = json.loads(p.read_text(encoding="utf-8"))["pages"]
        dup = [x for x in pages if x["route"] == "/employees"][0]
        assert dup["shell"] is False          # gone from the sidebar
        assert dup["route"] == "/employees"   # still reachable
        assert rep["dropped"] == 1

    def test_the_only_route_in_is_renamed_not_demoted(self, tmp_path):
        import json
        p = self._write(tmp_path, [
            {"title": "hr_admins", "route": "/hr-admins", "shell": True},
        ])
        reconcile_nav_flow(str(p))
        page = json.loads(p.read_text(encoding="utf-8"))["pages"][0]
        assert page["shell"] is True
        assert page["title"] == "HR Admins"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert reconcile_nav_flow(str(tmp_path / "nope.json"))["dropped"] == 0
