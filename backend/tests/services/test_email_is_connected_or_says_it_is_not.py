"""An integration that exists only in the definition looks like a broken app.

The owner's phrasebook marks "connect it to our Outlook" amber — "declared,
not connected: it needs a service and its key" — and lists what owners meet
first: the confirmation email that never came, the text that was never sent,
the mail that arrives from a weird address. These tests hold the two halves of
closing that: a connection that is real end to end, and a not-yet-connection
that says so where somebody will read it.

The rule that must not bend: a secret NAME travels, a secret VALUE never does
— not into the Blueprint, not into the ledger, not into a reply.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint.projection import connected_services, project_integrations
from services.blueprint.service import BlueprintService
from services.smith import email_connect as ec


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t",
                                name="Nurse Roster", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                              {"name": "email", "type": "string"}]}]}
    s.upsert("workflows", {
        "name": "Register Nurse", "purpose": "Register a nurse.",
        "trigger": {"kind": "manual"}, "launchedFrom": [],
        "steps": [
            {"key": "save", "name": "Save", "type": "action", "entity": "ENTITY-001",
             "config": {"actionType": "db_insert", "table": "nurses"}, "next": ["mail"]},
            {"key": "mail", "name": "Email the nurse", "type": "action",
             "config": {"actionType": "send_email", "to": "{{email}}",
                        "subject": "Welcome", "body": "You are registered."}},
        ]}, natural_key="Register Nurse")
    s.save()
    return s


# --- the owner names a service ---------------------------------------------------

@pytest.mark.parametrize("said, expected", [
    ("connect it to our Outlook", "Microsoft 365 / Outlook"),
    ("our Office 365 account", "Microsoft 365 / Outlook"),
    ("send the emails through our own account", "your own mail server"),
    ("send the emails through SendGrid", "SendGrid"),
    ("use google workspace please", "Google Workspace / Gmail"),
    ("resend", "Resend"),
])
def test_the_words_owners_use_reach_an_adapter(said, expected):
    """The owner's word is not a provider key: "Outlook", "Office 365" and
    "our own account" are all one adapter, and the vocabularies meet in
    exactly one place."""
    chosen = ec.service_for(said)
    assert chosen is not None and chosen.name == expected


@pytest.mark.parametrize("said", ["connect it to Xero", "text people through Twilio",
                                  "connect it to our payroll system", ""])
def test_a_service_with_no_adapter_is_not_matched_into_one(said):
    assert ec.service_for(said) is None


def test_connecting_records_the_service_and_the_names_of_its_secrets(svc):
    out = ec.connect(svc, service="connect it to our Outlook",
                     output_dir=str(svc.output_dir))
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    row = fresh.doc["integrations"][0]
    assert row["name"] == "Microsoft 365 / Outlook"
    assert row["provider"] == "smtp" and row["kind"] == "email"
    assert row["serves"] == "send_email"
    # NAMES ONLY, and they are the names the settings page actually renders —
    # a key Smith invents is a key the owner cannot set.
    from services.node_config_specs import keys_for_provider
    assert set(row["secretRefs"]) == {e.key for e in keys_for_provider("smtp")} | {"FORGE_EMAIL_FROM"}
    assert out["requirement"] and out["requirement"] in row["requirements"]


def test_one_service_carries_the_email_and_a_new_choice_retires_the_old(svc):
    ec.connect(svc, service="Outlook", output_dir=str(svc.output_dir))
    ec.connect(svc, service="Resend", output_dir=str(svc.output_dir))
    rows = BlueprintService.load(output_dir=str(svc.output_dir)).doc["integrations"]
    live = [r for r in rows if r.get("status") != "DEPRECATED"]
    assert [r["name"] for r in live] == ["Resend"]
    assert ec.declared({"integrations": rows})["name"] == "Resend"


def test_no_adapter_is_refused_with_the_reason_and_the_nearest_thing(svc):
    out = ec.run(str(svc.output_dir), service="Xero")
    assert out["applied"] is False and out["edited_paths"] == []
    assert "cannot connect" in out["reason"] and "Xero" in out["reason"]
    # The nearest thing that works, as sentences a click can say — the shape
    # `services.smith.limits` uses for every other honest refusal.
    assert any("email" in o.lower() for o in out["options"])
    assert any("Declare" in o for o in out["options"])
    # Nothing was written down as a side effect of refusing.
    assert BlueprintService.load(output_dir=str(svc.output_dir)).doc.get("integrations") in (None, [])


def test_a_pasted_key_is_not_recorded_anywhere(svc):
    """§42 names chat history first. A credential in the argument must not
    reach the Blueprint, a requirement's wording, or the reply."""
    out = ec.run(str(svc.output_dir), service="our own server, key SG.abcdefgh.ijklmnopqr")
    assert out["applied"] is False
    assert "SG.abcdefgh" not in out["reason"]
    doc = BlueprintService.load(output_dir=str(svc.output_dir)).doc
    assert "SG.abcdefgh" not in json.dumps(doc)


# --- connected, or honestly not --------------------------------------------------

def test_declared_without_the_key_is_reported_as_not_connected(svc, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr("services.platform_secrets.keys_set_for",
                        lambda output_dir, keys: set())
    out = ec.run(str(svc.output_dir), service="our Outlook")
    said = out["diff_summary"]
    assert out["connected"] is False
    assert "not yet connected" in said and "Settings" in said
    # The owner is told where to put it and what it is called, and never
    # asked for the value.
    assert "SMTP_HOST" in said and "smtp.office365.com" in said
    assert "Do not paste the value here" in said


def test_the_key_being_set_is_what_makes_it_connected(svc, monkeypatch):
    monkeypatch.setattr("services.platform_secrets.keys_set_for",
                        lambda output_dir, keys: {"SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"})
    out = ec.run(str(svc.output_dir), service="our Outlook")
    assert out["connected"] is True
    said = out["diff_summary"]
    assert "**Connected.**" in said
    # "It's sending from a weird address" — the from-address is the one thing
    # left, and it is named rather than left to be discovered by a customer.
    assert "FORGE_EMAIL_FROM" in said


def test_the_status_is_read_from_names_never_values(svc, monkeypatch):
    seen: list[list[str]] = []

    def fake(output_dir, keys):
        seen.append(list(keys))
        return {"SMTP_HOST"}

    monkeypatch.setattr("services.platform_secrets.keys_set_for", fake)
    ec.connect(svc, service="our Outlook", output_dir=str(svc.output_dir))
    conn = ec.status(svc.doc, str(svc.output_dir))
    assert conn.connected is True and conn.live_key == "SMTP_HOST"
    assert conn.missing == ["SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "FORGE_EMAIL_FROM"]
    # Only names went in, and only names came back.
    assert seen and all(isinstance(k, str) for k in seen[0])
    assert all(isinstance(k, str) for k in conn.set_keys)


def test_the_steps_that_send_are_named_so_the_gap_is_concrete(svc):
    assert ec.sending_steps(svc.doc) == [("Register Nurse", "Email the nurse")]
    out = ec.connect(svc, service="Resend", output_dir=str(svc.output_dir))
    assert "Email the nurse in Register Nurse" in ec.summarise(out)


# --- the app itself --------------------------------------------------------------

def test_the_projection_tells_the_app_which_service_it_sends_through(svc, tmp_path):
    ec.connect(svc, service="our Outlook", output_dir=str(svc.output_dir))
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    out = project_integrations(svc.doc, app)
    assert out["files"] == ["src/lib/integrations/connected.ts"]
    written = (app / "src" / "lib" / "integrations" / "connected.ts").read_text()
    assert '"send_email"' in written
    assert '"liveKey": "SMTP_HOST"' in written and "Microsoft 365 / Outlook" in written
    # The projected file is a map of NAMES. Nothing in it could be a secret.
    assert "password" not in written.lower() or "SMTP_PASSWORD" in written


def test_an_integration_that_serves_nothing_is_not_claimed_as_connected():
    """A row with no `serves` is a note for a developer. It must not reach the
    app as a connection, or the step would try to send through it."""
    doc = {"integrations": [
        {"id": "INT-001", "name": "Xero", "kind": "other", "provider": "xero",
         "secretRefs": ["XERO_CLIENT_SECRET"]},
    ]}
    assert connected_services(doc) == []


def test_a_row_claiming_to_serve_through_no_adapter_is_only_a_declaration(svc, tmp_path):
    """A hand-authored Blueprint can say `provider: "mailchimp", serves:
    "send_email"`. Nothing in the runtime can talk to it, so there is no key
    whose presence would make it work — it must not read as connected in the
    app or in what Smith says."""
    from services.smith.engine_blueprint_adapter import connection_lines

    doc = {"integrations": [{"id": "INT-001", "name": "Mailchimp", "kind": "email",
                             "provider": "mailchimp", "serves": "send_email",
                             "secretRefs": ["MAILCHIMP_API_KEY"]}]}
    assert connected_services(doc) == []
    line = connection_lines(doc, "")[0]
    assert line["serves"] == "" and line["connected"] is False


def test_a_retired_service_stops_being_the_connection(svc, tmp_path):
    ec.connect(svc, service="Resend", output_dir=str(svc.output_dir))
    from services.smith.definition_change import remove_integration
    remove_integration(svc, "Resend")
    assert ec.declared(svc.doc) is None
    assert connected_services(svc.doc) == []


# --- what Smith can say ----------------------------------------------------------

def test_smiths_context_says_connected_or_declared(svc, monkeypatch):
    from services.smith.engine_blueprint_adapter import connection_lines
    from services.smith_blueprint import Blueprint
    from services.smith_blueprint_context import _render_integrations

    monkeypatch.setattr("services.platform_secrets.keys_set_for",
                        lambda output_dir, keys: set())
    ec.connect(svc, service="our Outlook", output_dir=str(svc.output_dir))
    svc.doc.setdefault("integrations", []).append(
        {"id": "INT-099", "name": "Xero", "kind": "other", "provider": "xero",
         "secretRefs": ["XERO_CLIENT_SECRET"]})

    bp = Blueprint(project_id="p")
    bp.integrations = connection_lines(svc.doc, str(svc.output_dir))
    said = _render_integrations(bp)
    assert "DECLARED, NOT CONNECTED" in said and "SMTP_HOST" in said
    assert "Email the nurse in Register Nurse" in said
    # The service with no adapter is described as what it is, and Smith is
    # told in the same breath not to call it connected.
    assert "Xero" in said and "DECLARED ONLY" in said
    assert "XERO_CLIENT_SECRET" not in said or "DECLARED ONLY" in said


def test_a_sending_step_with_no_service_at_all_is_a_fact_in_the_context(svc):
    from services.smith.engine_blueprint_adapter import connection_lines
    from services.smith_blueprint import Blueprint
    from services.smith_blueprint_context import _render_integrations

    rows = connection_lines(svc.doc, str(svc.output_dir))
    assert rows and rows[0]["gap"] is True
    bp = Blueprint(project_id="p")
    bp.integrations = rows
    said = _render_integrations(bp)
    assert "nothing is connected" in said
    assert "Email the nurse in Register Nurse" in said


def test_the_verb_is_offered_dispatched_and_tooled(monkeypatch, tmp_path):
    """A verb nobody can reach is a verb that does not exist."""
    import services.smith_tools as smith_tools
    from services.smith.capabilities import GROUPS
    from services.smith.understand_ask import _PROMPT
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

    assert REQUIRED_BY_VERB["connect_service"] == {"integration"}
    assert "connect_service" in VERB_HELP and '"connect_service"' in _PROMPT
    assert any("connect_service" in verbs for _h, _w, verbs in GROUPS)
    # The chips a person clicks when Smith has to ask which service.
    from services.smith.slot_options import options_for
    offered = options_for("integration", {}, {"verb": "connect_service"})
    assert "Microsoft 365 / Outlook" in offered
    assert all(ec.service_for(o) is not None for o in offered)

    calls: list[str] = []
    monkeypatch.setattr("services.smith.email_connect.run",
                        lambda d, **k: calls.append(k.get("service") or "")
                        or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    out = smith_tools.READONLY_HANDLERS["connect_service"](str(tmp_path), {"integration": "our Outlook"})
    assert out["applied"] and calls == ["our Outlook"]
    assert smith_tools.READONLY_HANDLERS["connect_service"](str(tmp_path), {})["applied"] is False
