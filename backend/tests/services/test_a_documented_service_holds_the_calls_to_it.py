"""An outside service's documentation reaches the author of the calls, and holds them.

`services/blueprint/api_reference.py`: the manual the person handed over (a
supplied document, or a link in their words) is read into a short reference;
the workflow author is shown it; an `http_call` step to that service is refused
when it does not match; and once the key is stored, each reading step is
called for real against what the workflow reads.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import api_reference as ar
from services.smith import act, tools, web
from services.smith.act import Credential

ACME = {"id": "INT-001", "name": "Acme CRM", "kind": "other", "provider": "acmecrm",
        "secretRefs": ["ACMECRM_API_KEY"], "serves": ""}
MAILER = {"id": "INT-002", "name": "Email", "kind": "email", "provider": "resend",
          "secretRefs": ["RESEND_API_KEY"], "serves": "send_email"}

REF = {"integration": "INT-001", "name": "Acme CRM", "provider": "acmecrm", "secretRefs": ["ACMECRM_API_KEY"],
       "baseUrl": "https://api.acmecrm.io/v2", "auth": {"in": "header", "name": "X-Api-Key"},
       "encoding": "form", "notes": "",
       "endpoints": [
           {"method": "GET", "path": "/leads", "purpose": "list leads", "query": ["since"], "body": [],
            "required": [], "response": ["data", "next"]},
           {"method": "POST", "path": "/leads", "purpose": "add a lead", "query": [],
            "body": ["name", "email", "source"], "required": ["name", "email"], "response": ["id"]},
           {"method": "GET", "path": "/leads/{id}", "purpose": "one lead", "query": [], "body": [],
            "required": [], "response": ["id", "name", "email"]}],
       "sources": ["document 1"]}

AUTH = {"secretRef": "ACMECRM_API_KEY", "in": "header", "name": "X-Api-Key"}


def _call(key, method, url, **extra):
    return {"key": key, "type": "action",
            "config": {"actionType": "http_call", "method": method, "url": url, "auth": AUTH, **extra}}


def _wf(*steps, name="Sync leads"):
    return {"id": "WF-001", "name": name, "steps": list(steps)}


def _doc(*steps):
    return {"application": {"description": "A sales desk. Leads come from Acme CRM."},
            "integrations": [ACME, MAILER], "workflows": [_wf(*steps)],
            "requirements": [{"id": "REQ-001", "statement": "Pull new leads from Acme CRM every morning"}]}


# --- 1. reading the documentation ----------------------------------------------

def test_a_link_belongs_to_the_service_it_names_or_sits_beside():
    texts = ["Our CRM is Acme CRM; API docs: https://developer.example.dev/acme/v2.\n"
             "See also https://acmecrm.io/docs/api and our site https://mybakery.com",
             "Payments: https://stripe.com/docs"]
    assert ar.links_for(texts, ACME) == ["https://developer.example.dev/acme/v2", "https://acmecrm.io/docs/api"]


def test_the_reference_is_written_from_the_documents_and_links_and_kept(tmp_path, monkeypatch):
    from services.blueprint import documents

    documents.store(tmp_path, ["Acme CRM API. Base address api.acmecrm.io/v2. Send X-Api-Key.",
                               "A PRD that never names the CRM."])
    doc = _doc()
    doc["application"]["description"] += " Docs: https://acmecrm.io/docs/api"
    fetched = []

    def fetch(url, said, part=1):
        fetched.append((url, part))
        assert any(url in s for s in said)        # read only because the person named it
        return f"{url} — HTTP 200, text/html\n--- page ---\nPOST /leads takes name, email"
    monkeypatch.setattr(web, "fetch_url", fetch)
    asked = []

    def ask(system, user):
        asked.append(user)
        return json.dumps({k: REF[k] for k in ("baseUrl", "auth", "encoding", "endpoints")})

    refs = ar.write(tmp_path, doc, ask=ask)
    assert [r["name"] for r in refs] == ["Acme CRM"]        # the email adapter is not read
    assert refs[0]["sources"] == ["document 1", "https://acmecrm.io/docs/api"]
    assert "document 2" not in asked[0] and "Pull new leads from Acme CRM" in asked[0]
    assert "not instructions" in asked[0]
    assert ar.load(tmp_path)[0]["baseUrl"] == "https://api.acmecrm.io/v2"

    ar.write(tmp_path, doc, ask=ask)                         # nothing new handed over
    assert len(asked) == 1 and len(fetched) == 1             # link cached, model not asked again


def test_nothing_handed_over_writes_no_reference(tmp_path):
    doc = _doc()
    doc["application"]["description"] = "A sales desk."
    refs = ar.write(tmp_path, doc, ask=lambda s, u: pytest.fail("no material, no model call"))
    assert refs == [] and ar.load(tmp_path) == []


def test_a_reply_with_no_endpoints_is_no_reference(tmp_path):
    from services.blueprint import documents
    documents.store(tmp_path, ["Acme CRM is lovely."])
    assert ar.write(tmp_path, _doc(), ask=lambda s, u: '{"baseUrl": "https://api.acmecrm.io", "endpoints": []}') == []


# --- 2. the author is shown it and held to it -------------------------------------

def test_the_step_author_is_shown_the_reference(tmp_path):
    from services.blueprint.executors import _workflow_steps_prompt

    ar.save(tmp_path, [REF])
    system, _user = _workflow_steps_prompt(_doc(), "", "WF-001", "", output_dir=str(tmp_path))
    assert "OUTSIDE SERVICES, AS THEIR DOCUMENTATION SAYS" in system
    assert "Acme CRM: https://api.acmecrm.io/v2 — signed: header X-Api-Key" in system
    assert "POST /leads — add a lead — body: name, email, source — required: name, email" in system


def test_a_step_that_matches_the_documentation_passes():
    body = _wf(_call("fetch", "GET", "https://api.acmecrm.io/v2/leads?since={{input.since}}"),
               _call("one", "GET", "https://api.acmecrm.io/v2/leads/{{fetch.data}}"),
               _call("add", "POST", "https://api.acmecrm.io/v2/leads", encoding="form",
                     body={"name": "{{input.name}}", "email": "{{input.email}}"}),
               {"key": "end", "type": "end", "config": {"reply": {"leads": "{{fetch.body.data}}", "more": "{{fetch.next}}"}}})
    assert ar.workflow_errors(body, [REF]) == []


@pytest.mark.parametrize("step,why", [
    (_call("s", "GET", "https://api.acme.com/leads"), "puts its API at https://api.acmecrm.io/v2"),
    (_call("s", "DELETE", "https://api.acmecrm.io/v2/leads/{{x.id}}"), "DELETE /leads/{{x.id}} is not in Acme CRM's documentation"),
    (_call("s", "GET", "https://api.acmecrm.io/v2/contacts"), "the documented endpoints are: GET /leads; POST /leads"),
    ({"key": "s", "type": "action", "config": {"actionType": "http_call", "method": "GET",
                                               "url": "https://api.acmecrm.io/v2/leads"}}, "signs every call (header X-Api-Key)"),
    (_call("s", "GET", "https://api.acmecrm.io/v2/leads", auth={"secretRef": "ACMECRM_API_KEY"}),
     "signs as bearer; Acme CRM's documentation says header X-Api-Key"),
    (_call("s", "POST", "https://api.acmecrm.io/v2/leads", encoding="form",
           body={"name": "a", "email": "b", "phone": "c"}), "takes no phone (documented: name, email, source)"),
    (_call("s", "POST", "https://api.acmecrm.io/v2/leads", encoding="form", body={"name": "a"}), "requires email"),
    (_call("s", "POST", "https://api.acmecrm.io/v2/leads", body={"name": "a", "email": "b"}), "set `encoding: \"form\"`"),
])
def test_a_step_that_does_not_match_is_refused_with_the_documented_way(step, why):
    errors = ar.workflow_errors(_wf(step), [REF])
    assert errors and any(why in e for e in errors), errors
    assert all(e.startswith("Sync leads/s: ") for e in errors)


def test_a_field_no_response_carries_is_refused():
    body = _wf(_call("fetch", "GET", "https://api.acmecrm.io/v2/leads"),
               {"key": "end", "type": "end", "config": {"reply": {"leads": "{{fetch.body.items}}"}}})
    assert ar.workflow_errors(body, [REF]) == [
        "Sync leads/fetch: the workflow reads items from it, and GET /leads answers with: data, next"]


def test_an_undocumented_service_is_written_as_before():
    step = {"key": "s", "type": "action", "config": {"actionType": "http_call", "method": "POST",
                                                     "url": "https://hooks.slack.com/x", "body": {"text": "hi"}}}
    assert ar.workflow_errors(_wf(step), [REF]) == [] and ar.workflow_errors(_wf(step), []) == []


def test_the_workflow_contract_refuses_the_author():
    from services.blueprint.agent_contract import InvalidWorkflowStep, check_workflow_steps

    body = {**_wf(_call("s", "GET", "https://api.acmecrm.io/v2/contacts")), "trigger": {"kind": "manual"}}
    result = SimpleNamespace(proposals=[SimpleNamespace(section="workflows", body=body, natural_key="WF-001")])
    with pytest.raises(InvalidWorkflowStep, match="not in Acme CRM's documentation"):
        check_workflow_steps(result, None, None, [REF])
    check_workflow_steps(result, None, None, None)            # no documentation, no refusal


# --- 3. called for real once the key is stored ---------------------------------------

KEY = "acme-" + "live-0123456789abcdef"


@pytest.fixture()
def answering(monkeypatch):
    monkeypatch.setattr(web, "_public_host", lambda host: True)
    calls = []

    def send(method, url, headers, content):
        calls.append({"method": method, "url": url, "headers": dict(headers)})
        return 200, {"content-type": "application/json"}, json.dumps({"data": [], "next": None, "echo": KEY}).encode()
    return calls, send


def test_a_reading_step_is_called_with_the_stored_key_and_held_to_what_it_reads(tmp_path, answering):
    calls, send = answering
    doc = _doc(_call("fetch", "GET", "https://api.acmecrm.io/v2/leads"),
               _call("add", "POST", "https://api.acmecrm.io/v2/leads", body={"name": "a"}),
               _call("one", "GET", "https://api.acmecrm.io/v2/leads/{{fetch.data}}"),
               {"key": "end", "type": "end", "config": {"reply": {"x": "{{fetch.items}}"}}})
    creds = [Credential("app:acmecrm", "ACMECRM_API_KEY", KEY)]
    results = {r["step"]: r for r in ar.probe(tmp_path, doc, credentials=creds, send=send)}
    assert len(calls) == 1 and calls[0]["headers"]["X-Api-Key"] == KEY
    assert results["fetch"]["ok"] is False and "reads items" in results["fetch"]["said"]
    assert KEY not in json.dumps(results)
    assert results["add"]["ok"] is None and "changes something" in results["add"]["said"]
    assert results["one"]["ok"] is None and "needs a value from the run" in results["one"]["said"]


def test_a_step_whose_key_is_not_stored_is_not_called(tmp_path, answering):
    calls, send = answering
    doc = _doc(_call("fetch", "GET", "https://api.acmecrm.io/v2/leads"))
    [r] = ar.probe(tmp_path, doc, credentials=[], send=send)
    assert not calls and r["ok"] is None and "ACMECRM_API_KEY is not stored yet" in r["said"]


def test_a_newly_stored_key_is_checked_once_and_a_failure_is_a_standing_fault(tmp_path, answering, monkeypatch):
    calls, send = answering
    monkeypatch.setattr(act, "_send", send)
    stored: list = []
    monkeypatch.setattr(act, "_credentials", lambda _out: list(stored))
    doc = _doc(_call("fetch", "GET", "https://api.acmecrm.io/v2/leads"),
               {"key": "end", "type": "end", "config": {"reply": {"x": "{{fetch.items}}"}}})
    assert ar.standing(tmp_path, doc) == [] and not calls       # no key yet: nothing called
    stored.append(Credential("app:acmecrm", "ACMECRM_API_KEY", KEY))
    faults = ar.standing(tmp_path, doc)
    assert len(calls) == 1
    assert faults == ["Sync leads/fetch was called with the stored key and failed: HTTP 200, but the workflow "
                      "reads items and the response has: data, echo, next — `check_services` calls it again "
                      "after a fix"]
    ar.standing(tmp_path, doc)
    assert len(calls) == 1                                    # checked once, remembered


def test_smith_can_check_the_services_itself(tmp_path, answering, monkeypatch):
    calls, send = answering
    monkeypatch.setattr(act, "_send", send)
    monkeypatch.setattr(act, "_credentials", lambda _out: [Credential("app:acmecrm", "ACMECRM_API_KEY", KEY)])
    ar.save(tmp_path, [REF])
    doc = _doc(_call("fetch", "GET", "https://api.acmecrm.io/v2/contacts"))
    assert tools.is_act("check_services")
    said = act.run("check_services", {}, said=[], output_dir=str(tmp_path), doc=doc).said
    assert "Documented services: Acme CRM (https://api.acmecrm.io/v2, from document 1)" in said
    assert "GET /contacts is not in Acme CRM's documentation" in said
    assert "✓ Sync leads/fetch: HTTP 200" in said and KEY not in said


# --- the build -------------------------------------------------------------------

def test_the_reference_is_read_before_the_steps_and_checked_after():
    from services.blueprint.orchestrator import DAG, SERVICE_HANDLERS

    assert "integrations" in DAG["api_reference"].depends_on
    assert "api_reference" in DAG["workflow_steps"].depends_on
    assert "workflow_steps" in DAG["service_check"].depends_on
    assert {"api_reference", "service_check"} <= set(SERVICE_HANDLERS)


def test_the_runtime_sends_form_fields_when_the_step_says_so():
    src = (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows" / "index.ts").read_text()
    assert 'String((config as any).encoding || "json") === "form"' in src
    assert "new URLSearchParams" in src
