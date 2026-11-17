"""Five platform bugs a ride-hailing driver app + admin dashboard (built through Forge, then driven in a
browser and over HTTP, 2026-11-11) exposed. Each test is the smallest statement of one of them.

1. a REQUIRED place was seeded as nothing, so no ride / location / earnings row could be saved
2. the account signup asked a new driver for their own rating and total rides, and started them online
3. nothing checked that a phone number was a phone number
4. every workflow could be run by every signed-in person, because assembly deleted the roles file
5. a "completed at" column defaulted to now, so every new ride was born finished
"""
from pathlib import Path

from services.blueprint import account_model, assembly
from services.blueprint.projection import _seed_value, drizzle_column

BACKEND = Path(__file__).resolve().parents[2]


# -- 1. seeding ---------------------------------------------------------------------------------

def test_a_required_place_is_seeded_near_the_applications_own_region_and_an_optional_one_stays_empty():
    required = {"name": "pickupLocation", "type": "location", "required": True}
    optional = {"name": "currentLocation", "type": "location", "required": False}
    doc_in = {"product": {"locale": "en", "currency": "INR"}}
    anchor = __import__("services.blueprint.projection", fromlist=["_seed_anchor"])._seed_anchor(doc_in)
    place = _seed_value(required, "Ride", 1, anchor=anchor)
    assert set(place) == {"lat", "lng"}
    assert abs(place["lat"] - 12.9716) < 0.05 and abs(place["lng"] - 77.5946) < 0.05, place  # India, from the currency
    assert _seed_value(optional, "Driver", 1, anchor=anchor) is None, "a person's own position is still never invented"
    # rows are spread a few streets apart, not stacked on one point
    assert _seed_value(required, "Ride", 1, anchor=anchor) != _seed_value(required, "Ride", 2, anchor=anchor)


def test_the_seed_template_does_not_assume_an_account_tables_email_is_unique():
    src = (BACKEND / "templates" / "runtime" / "seed.ts").read_text(encoding="utf-8")
    keyed = src[src.index("const keyed = emailCol"):src.index("ids[norm(t.name)] = [...existingIds, ...got]")]
    assert "onConflictDoNothing({ target: emailCol })" not in keyed, "a conflict target on a column with no unique index is refused by Postgres"
    assert ".where(eq(emailCol" in keyed and "onConflictDoNothing()" in keyed


# -- 2. the account signup ----------------------------------------------------------------------

def _driver_doc():
    def f(name, ftype="string", **kw):
        return {"name": name, "type": ftype, **kw}
    return {
        "roles": [{"id": "ROLE-001", "name": "Driver"}],
        "security": {"signupRole": "ROLE-001"},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Driver", "account": True, "fields": [
            f("id", "uuid", primaryKey=True), f("name", required=True), f("phone", required=True),
            f("rating", "number", required=True), f("totalRides", "number", required=True),
            f("verificationNotes", "text"), f("lastActiveAt", "timestamp"),
            f("verificationStatus", "enum", required=True, enumValues=["pending_verification", "approved"]),
            f("availabilityStatus", "enum", required=True, enumValues=["online", "offline"]),
            f("drivingLicenseNumber")]}]},
        "workflows": [
            {"id": "FLOW-1", "name": "Go online", "steps": [{"entity": "ENTITY-001", "config": {"actionType": "db_update", "values": {"availabilityStatus": "online"}}}]},
            {"id": "FLOW-2", "name": "Go offline", "steps": [{"entity": "ENTITY-001", "config": {"actionType": "db_update", "values": {"availabilityStatus": "offline"}}}]},
            {"id": "FLOW-4", "name": "Approve driver", "steps": [{"entity": "ENTITY-001", "config": {"actionType": "db_update", "values": {"verificationStatus": "approved"}}}]},
            {"id": "FLOW-5", "name": "Submit onboarding", "steps": [{"entity": "ENTITY-001", "config": {"actionType": "db_update", "values": {"verificationStatus": "pending_verification"}}}]},
            # a formula over another step's output is the process's own value, not something the person typed
            {"id": "FLOW-3", "name": "Complete ride", "steps": [{"entity": "ENTITY-001", "config": {"actionType": "db_update", "values": {"totalRides": "{{find_driver.totalRides + 1}}"}}}]},
        ],
    }


def test_signup_asks_a_driver_only_what_a_driver_knows_about_themselves():
    asked = [f["name"] for f in account_model.account_fields(_driver_doc())]
    assert asked == ["name", "phone", "drivingLicenseNumber"], asked
    for never in ("rating", "totalRides", "verificationNotes", "lastActiveAt", "verificationStatus", "availabilityStatus"):
        assert never not in asked, never


def test_a_new_account_starts_offline_and_pending_and_with_nothing_awarded():
    start = account_model.account_initial(_driver_doc())
    assert start["availabilityStatus"] == "offline", "every status value is written by some process: the one meaning 'not yet' wins, not the first listed"
    assert start["verificationStatus"] == "pending_verification"
    assert start["rating"] == 0 and start["totalRides"] == 0


def test_the_signup_route_checks_that_a_phone_is_a_phone():
    # the check lives where every way of making an account reads it (password sign-up and a provider's both)
    src = (BACKEND / "templates" / "app-foundation" / "src" / "lib" / "account-row.ts").read_text(encoding="utf-8")
    assert 'f.kind === "tel"' in src and "must be a phone number" in src
    assert 'f.kind === "email"' in src and "must be an email address" in src


# -- 4. who may run a workflow ------------------------------------------------------------------

def test_assembly_never_deletes_the_roles_that_say_who_may_run_each_workflow():
    assert "src/lib/workflows/launch-roles.ts" in assembly.PROJECTED_PATHS, (
        "the runtime injector clears src/lib/workflows of everything not on this list and writes an EMPTY roles "
        "file: every workflow was then open to every signed-in person")


# -- 5. timestamps ------------------------------------------------------------------------------

def test_only_what_is_stamped_at_creation_defaults_to_now():
    stamped, _ = drizzle_column({"name": "createdAt", "type": "timestamp", "required": True})
    assert ".defaultNow()" in stamped
    for later in ("completedAt", "readAt", "deletedAt", "archivedAt"):
        line, _ = drizzle_column({"name": later, "type": "timestamp"})
        assert ".defaultNow()" not in line, f"{later} records something that happens later: a ride must not be born completed"


# -- 6. a seeded login starts where a signup does -----------------------------------------------

def test_the_seed_gives_each_login_the_same_starting_values_as_a_signup():
    src = (BACKEND / "templates" / "runtime" / "seed.ts").read_text(encoding="utf-8")
    ensure = src[src.index("async function ensureAccountRow"):src.index("await resolveRequiredFks(accountTable, row);")]
    assert "ACCOUNT_INITIAL" in ensure, (
        "the generic filler wrote the person's NAME into a required enum: the demo admin showed on the "
        "dashboard as a driver whose availability was 'Default Admin'")


# -- 7. what is painted never reads the clock ---------------------------------------------------

def test_the_kit_author_is_told_a_painted_time_never_reads_now_or_the_viewers_zone():
    from services.blueprint import component_kit
    text = Path(component_kit.__file__).read_text(encoding="utf-8")
    assert "NOTHING THAT IS PAINTED READS THE CLOCK" in text
    assert "hydration error" in text and "useState(() => Date.now())" in text


# -- 8. an uploaded file is never served as a page ----------------------------------------------

def test_uploads_are_limited_to_documents_and_pictures_and_never_served_as_a_page():
    files = BACKEND / "templates" / "runtime" / "api-files"
    up = (files / "upload-route.ts").read_text(encoding="utf-8")
    assert "ALLOWED_TYPE" in up and "BLOCKED_NAME" in up and "status: 415" in up and "MAX_BYTES" in up
    for ext in ("html", "svg", "php", "js", "exe"):
        assert ext in up.split("BLOCKED_NAME =")[1].split("\n")[0], ext
    assert "String(err)" not in up, "an upload failure must not hand the raw error to the browser"
    for name in ("download-route.ts", "preview-route.ts"):
        src = (files / name).read_text(encoding="utf-8")
        assert "X-Content-Type-Options" in src and "nosniff" in src, name
        assert "attachment" in src and "sandbox" in src, name


# -- 9. a failed workflow reads as words --------------------------------------------------------

def test_a_workflow_failure_never_shows_the_person_the_database_driver_text():
    src = (BACKEND / "templates" / "runtime" / "workflows" / "engine.ts").read_text(encoding="utf-8")
    assert "export function plainFailure" in src
    assert "plainFailure(err instanceof Error" in src, "the failed result must go through it"
    assert "is already in use" in src and "PostgresError" in src


# -- 10. the menu opens the tab it names --------------------------------------------------------

def test_a_menu_entry_opens_a_saved_view_only_when_the_page_has_that_view():
    import tempfile, json
    from services.blueprint.projection import project_shell
    doc = {
        "navigation": {"tree": [{"label": "Drivers", "page": "PAGE-1", "children": [
            {"label": "Pending", "page": "PAGE-1", "section": "pending", "view": "pending_verification"}]}]},
        "pages": [{"id": "PAGE-1", "route": "/drivers", "sections": [{"key": "pending", "placement": "tab"}], "views": []}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        project_shell(doc, tmp)
        shell = (Path(tmp) / "src" / "schemas" / "shell.json").read_text(encoding="utf-8")
    assert "/drivers?tab=pending" in shell and "view=pending_verification" not in shell
    doc["pages"][0]["views"] = [{"key": "pending_verification", "label": "Pending"}]
    with tempfile.TemporaryDirectory() as tmp:
        project_shell(doc, tmp)
        shell = (Path(tmp) / "src" / "schemas" / "shell.json").read_text(encoding="utf-8")
    assert "/drivers?view=pending_verification" in shell, "a declared view is still opened by its key"


# -- 11. the rail's active item is readable on whatever colour the rail is -----------------------

def test_the_rails_active_and_hover_colours_come_from_its_own_text_not_a_guess_about_light_or_dark():
    src = (BACKEND.parent / "packages" / "library" / "src" / "components" / "SideNav" / "SideNav.tsx").read_text(encoding="utf-8")
    assert '"--tf-atext" as string]: cText' in src, "white-on-lavender: the active text was white whenever the rail colour was not a #rrggbb"
    assert 'light ? cAccent : "#fff"' not in src


# -- 12. a rail is dark when its own colour is dark ----------------------------------------------

def test_the_shell_judges_the_rail_by_its_colour_not_the_apps_tone():
    src = (BACKEND / "templates" / "app-foundation" / "src" / "app" / "(dashboard)" / "layout.tsx").read_text(encoding="utf-8")
    assert "function railIsDark" in src
    assert 'const dark = props.mode !== "light";' not in src, "a dark app with a light rail got white-on-lavender menu text"


# -- 13. a dark rail is painted with a dark surface -----------------------------------------------

def test_a_dark_rail_on_a_dark_app_is_not_painted_with_a_light_inverse():
    import json, tempfile
    from services.blueprint.projection import project_shell

    def rail(inverse):
        doc = {"navigation": {"tree": [{"label": "Home", "page": "P1"}]}, "pages": [{"id": "P1", "route": "/"}],
               "designSystem": {"colors": {"inverse": inverse}, "shell": {"tone": "dark"}}}
        with tempfile.TemporaryDirectory() as tmp:
            project_shell(doc, tmp)
            text = (Path(tmp) / "src" / "schemas" / "shell.json").read_text(encoding="utf-8")
        return json.loads(text)
    light_inverse = json.dumps(rail("#EDEBFF"))
    assert "var(--inverse))" not in light_inverse and "hsl(var(--card))" in light_inverse
    dark_inverse = json.dumps(rail("#0B1220"))
    assert "hsl(var(--inverse))" in dark_inverse, "a light app's dark rail still uses its dark inverse"
