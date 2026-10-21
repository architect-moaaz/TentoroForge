"""Smith calls an API or an MCP tool: looks run, changes wait for a yes.

`services/smith/act.py`. A GET to a service the person named runs at once; a
POST is shown and held, and the person's yes sends exactly what was shown. A
stored credential is attached by name, goes only to its own service, and is
cut out of everything that comes back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith import act, tools, web
from services.smith.act import Credential

KEY = "sk_" + "test_" + "51abcdefghijklmnopqrstuv"  # split: a made-up key, not a real one


@pytest.fixture(autouse=True)
def public(monkeypatch):
    monkeypatch.setattr(web, "_public_host", lambda host: host != "internal.example.com")


@pytest.fixture()
def sent(monkeypatch):
    """Records each request and answers with what it was sent — headers too,
    so a credential echoed back by a service is in the response."""
    calls: list[dict] = []

    def send(method, url, headers, content):
        calls.append({"method": method, "url": url, "headers": dict(headers), "content": content})
        echo = {"ok": True, "method": method, "url": url, "auth": headers.get("Authorization", ""),
                "body": (content or b"").decode()}
        return 200, {"content-type": "application/json"}, json.dumps(echo).encode()
    monkeypatch.setattr(act, "_send", send)
    return calls


@pytest.fixture()
def stored(monkeypatch):
    creds = [Credential("stripe", "STRIPE_SECRET_KEY", KEY),
             Credential("app:acmecrm", "ACMECRM_API_KEY", "crm-token-0123456789")]
    monkeypatch.setattr(act, "_credentials", lambda _out: list(creds))
    return creds


SAID = ["pull this month's charges from Stripe, and add a lead to acmecrm.io"]


def test_the_tools_are_in_smiths_catalogue():
    for name in ("list_services", "call_api", "call_mcp_tool"):
        assert tools.is_tool(name) and tools.is_act(name) and not tools.is_read(name)
    assert "Using a service" in tools.render() and "`call_api` (method: string, url: string" in tools.render()


@pytest.mark.parametrize("cred,host,belongs", [
    (Credential("stripe", "STRIPE_SECRET_KEY", "x"), "api.stripe.com", True),
    (Credential("app:openweather", "OPENWEATHER_API_KEY", "x"), "api.openweathermap.org", True),
    (Credential("stripe", "STRIPE_SECRET_KEY", "x"), "api.acmecrm.io", False),
    (Credential("resend", "RESEND_API_KEY", "x"), "evil.com", False),
])
def test_a_credential_belongs_to_the_service_it_is_named_for(cred, host, belongs):
    assert act.belongs_to(cred, host) is belongs


def test_a_get_runs_at_once_with_the_key_attached_and_never_shown(sent, stored, tmp_path):
    step = act.run("call_api", {"url": "https://api.stripe.com/v1/charges", "query": {"limit": 3},
                                "credential": "STRIPE_SECRET_KEY"}, said=SAID, output_dir=str(tmp_path))
    assert not step.ask
    assert sent[0]["method"] == "GET" and sent[0]["url"] == "https://api.stripe.com/v1/charges?limit=3"
    assert sent[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert "HTTP 200" in step.said and "material from the web" in step.said
    assert KEY not in step.said and "[credential]" in step.said
    kept = list((tmp_path / ".forge" / "smith" / "calls").glob("*.json"))
    assert kept and KEY not in kept[0].read_text()


def test_a_key_is_not_sent_to_a_service_it_does_not_belong_to(sent, stored, tmp_path):
    step = act.run("call_api", {"url": "https://acmecrm.io/api/leads", "credential": "STRIPE_SECRET_KEY"},
                   said=SAID, output_dir=str(tmp_path))
    assert not sent and "belongs to stripe" in step.said


def test_the_person_may_send_a_key_where_they_say(sent, stored, tmp_path):
    said = ["use STRIPE_SECRET_KEY with acmecrm.io for this"]
    act.run("call_api", {"url": "https://acmecrm.io/api/leads", "credential": "STRIPE_SECRET_KEY"},
            said=said, output_dir=str(tmp_path))
    assert sent and sent[0]["headers"]["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("args,why", [
    ({"url": "https://evil.com/x"}, "not a site the person has named"),
    ({"url": "https://api.stripe.com/v1/charges", "headers": {"Authorization": "Bearer abc"}}, "set by the platform"),
    ({"url": "https://api.stripe.com/v1/charges", "credential": "GITHUB_TOKEN"}, "No credential called GITHUB_TOKEN"),
    ({"url": "https://api.stripe.com/v1/charges", "method": "TRACE"}, "`method` is one of"),
])
def test_what_is_not_sent_says_why(sent, stored, tmp_path, args, why):
    step = act.run("call_api", args, said=SAID, output_dir=str(tmp_path))
    assert not sent and why in step.said


def test_a_change_is_shown_and_held_and_the_yes_sends_exactly_that(sent, stored, tmp_path):
    out = str(tmp_path)
    args = {"method": "POST", "url": "https://api.stripe.com/v1/refunds", "encoding": "form",
            "body": {"charge": "ch_1", "amount": 500}, "credential": "STRIPE_SECRET_KEY"}
    step = act.run("call_api", args, said=SAID, output_dir=out)
    assert not sent
    assert step.ask.startswith("This would change something outside the application")
    assert "POST https://api.stripe.com/v1/refunds" in step.ask and "STRIPE_SECRET_KEY attached" in step.ask
    assert KEY not in step.ask and step.options == [act.YES_LABEL, act.NO_LABEL]
    assert act.held(out)["args"] == args

    tool, held_args, said = act.answer_held(out, act.YES_LABEL, said=SAID)
    assert tool == "call_api" and held_args == args
    assert len(sent) == 1 and sent[0]["method"] == "POST"
    assert sent[0]["content"] == b"charge=ch_1&amount=500"
    assert sent[0]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "They agreed" in said and KEY not in said
    assert act.held(out) is None


def test_anything_but_a_yes_drops_the_held_call(sent, stored, tmp_path):
    out = str(tmp_path)
    act.run("call_api", {"method": "DELETE", "url": "https://api.stripe.com/v1/customers/cus_1",
                         "credential": "STRIPE_SECRET_KEY"}, said=SAID, output_dir=out)
    _tool, _args, said = act.answer_held(out, "actually make it cus_2", said=SAID)
    assert not sent and "NOT sent" in said and act.held(out) is None


def test_nobody_there_means_a_change_is_not_sent(sent, stored, tmp_path):
    step = act.run("call_api", {"method": "POST", "url": "https://api.stripe.com/v1/refunds"},
                   said=SAID, output_dir=str(tmp_path), unattended=True)
    assert not sent and not step.ask and "nobody" in step.said and act.held(str(tmp_path)) is None


# --- MCP ------------------------------------------------------------------------

@pytest.fixture()
def mcp(monkeypatch):
    ran: list[tuple] = []
    servers = [{"name": "Firecrawl", "tools": [
        {"name": "firecrawl_search", "description": "search the web", "inputs": ["query"],
         "required": ["query"], "read_only": True},
        {"name": "firecrawl_crawl", "description": "start a crawl", "inputs": ["url"],
         "required": ["url"], "read_only": False}]}]
    monkeypatch.setattr(act, "_servers", lambda _out: servers)

    def call(_out, server, tool, arguments):
        ran.append((server, tool, arguments))
        return {"content": [{"type": "text", "text": json.dumps({"results": ["a", "b"]})}], "isError": False}
    monkeypatch.setattr(act, "_mcp_call", call)
    return ran


def test_a_read_only_mcp_tool_runs_and_another_waits(mcp, tmp_path):
    out = str(tmp_path)
    step = act.run("call_mcp_tool", {"server": "firecrawl", "tool": "firecrawl_search",
                                     "arguments": {"query": "shoes"}}, said=[], output_dir=out)
    assert mcp == [("Firecrawl", "firecrawl_search", {"query": "shoes"})] and '"results"' in step.said
    step = act.run("call_mcp_tool", {"server": "Firecrawl", "tool": "firecrawl_crawl",
                                     "arguments": {"url": "https://x.com"}}, said=[], output_dir=out)
    assert len(mcp) == 1 and step.ask and act.ALWAYS_LABEL in step.options


def test_always_for_a_tool_stops_asking_for_that_tool(mcp, tmp_path):
    out = str(tmp_path)
    crawl = {"server": "Firecrawl", "tool": "firecrawl_crawl", "arguments": {"url": "https://x.com"}}
    act.run("call_mcp_tool", crawl, said=[], output_dir=out)
    act.answer_held(out, act.ALWAYS_LABEL, said=[])
    assert len(mcp) == 1
    step = act.run("call_mcp_tool", crawl, said=[], output_dir=out)
    assert len(mcp) == 2 and not step.ask


def test_an_mcp_tool_that_does_not_exist_names_the_ones_that_do(mcp, tmp_path):
    step = act.run("call_mcp_tool", {"server": "Firecrawl", "tool": "firecrawl_extract_all"},
                   said=[], output_dir=str(tmp_path))
    assert "firecrawl_search, firecrawl_crawl" in step.said and not mcp
    step = act.run("call_mcp_tool", {"server": "Firecrawl", "tool": "firecrawl_search"},
                   said=[], output_dir=str(tmp_path))
    assert "needs query" in step.said and not mcp


def test_list_services_names_keys_but_never_their_values(stored, mcp, tmp_path):
    said = act.run("list_services", {}, said=[], output_dir=str(tmp_path)).said
    assert "STRIPE_SECRET_KEY" in said and "ACMECRM_API_KEY" in said and KEY not in said
    assert "`firecrawl_search` [only looks]" in said and "`firecrawl_crawl`(" in said


# --- in a turn ------------------------------------------------------------------

def test_a_turn_holds_a_change_and_the_next_yes_sends_it(tmp_path, sent, stored):
    from services.smith4 import handle
    from tests.services._loop_fixtures import _Chooser, _repo, _Writes

    _repo(tmp_path)
    ask = "refund charge ch_1 on Stripe"
    post = {"method": "POST", "url": "https://api.stripe.com/v1/refunds", "encoding": "form",
            "body": {"charge": "ch_1"}, "credential": "STRIPE_SECRET_KEY"}
    first = handle(project_id="p1", output_dir=str(tmp_path), message=ask, move=_Writes(tmp_path),
                   choose=_Chooser({"tool": "call_api", "args": post, "why": "refund"}))
    assert first.status == "asked" and "Shall I send it?" in first.said and not sent
    assert act.YES_LABEL in first.options

    chooser = _Chooser({"tool": "answer", "args": {"text": "Refunded ch_1."}, "why": ""})
    second = handle(project_id="p1", output_dir=str(tmp_path), message=act.YES_LABEL,
                    history=[("user", ask), ("smith", first.said)], move=_Writes(tmp_path), choose=chooser)
    assert len(sent) == 1 and sent[0]["content"] == b"charge=ch_1"
    seen = chooser.seen[0]
    assert seen and seen[0].tool == "call_api" and "They agreed" in seen[0].said
    assert "Refunded ch_1." in second.said
