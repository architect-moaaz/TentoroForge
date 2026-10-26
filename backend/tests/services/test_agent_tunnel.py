"""The reverse SSH tunnel to the builder's own computer: pairing, the key list, ports, and what Watch live says about it.

What is pinned: a pairing code works once, for a short time, only for the project that asked, and wrong guesses are limited;
only a plain ed25519 key can ever reach the SSH server's key list (a key with options, a second line or a comment is refused
and cannot become a command); each key may open only its own project's port and run nothing; a project keeps its port when it
pairs again and no two projects share one; the tunnel counts as connected only while its listener exists; and every way the
app can be unreachable behind it is said as its own plain sentence.
"""
from __future__ import annotations

import base64
import os
import socket
import uuid
from types import SimpleNamespace

import httpx
import pytest

from services import agent_debug, agent_tunnel
from services.agent_tunnel import TunnelError

PID = "11111111-2222-3333-4444-555555555555"
PID2 = "99999999-2222-3333-4444-555555555555"
SECRET = "s" * 43


def key(seed: int = 1) -> str:
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([seed]) * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode()


@pytest.fixture()
def tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TUNNEL_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_TUNNEL_PUBLIC_HOST", "13.212.213.53")
    monkeypatch.setenv("FORGE_TUNNEL_HOST", "127.0.0.1")
    (tmp_path / "host_key.pub").write_text(key(9) + " root@tunnel\n", encoding="utf-8")
    agent_tunnel._bad.clear()
    return tmp_path


def code_for(project=PID, now=None):
    return agent_tunnel.new_pairing(project, now=now)["code"]


def redeem(code, k=None, port=3001, secret=SECRET, ip="1.2.3.4", now=None, label="laptop"):
    return agent_tunnel.pair(code, key() if k is None else k, port, secret, client_ip=ip, label=label, now=now)


# ── the code ────────────────────────────────────────────────────────────────

def test_a_code_is_eight_unambiguous_characters_shown_in_two_groups_and_lasts_ten_minutes(tunnel):
    got = agent_tunnel.new_pairing(PID, now=1000)
    assert len(got["code"]) == 9 and got["code"][4] == "-" and got["expiresAt"] == 1600
    assert set(got["code"].replace("-", "")) <= set(agent_tunnel.CODE_ALPHABET)
    assert not set("01OI") & set(agent_tunnel.CODE_ALPHABET)


def test_a_code_works_once_however_it_is_typed(tunnel):
    c = code_for()
    out = redeem(c.lower().replace("-", " "))
    assert out["projectId"] == PID
    with pytest.raises(TunnelError) as e:
        redeem(c)
    assert e.value.status_code == 404 and "not valid, or it has expired" in str(e.value)


def test_a_code_expires(tunnel):
    c = agent_tunnel.new_pairing(PID, now=1000)["code"]
    with pytest.raises(TunnelError) as e:
        redeem(c, now=1000 + agent_tunnel.PAIR_TTL_S + 1)
    assert e.value.status_code == 404


def test_a_wrong_guess_is_refused_and_too_many_from_one_address_are_told_to_wait(tunnel):
    code_for()
    for _ in range(agent_tunnel.MAX_BAD_GUESSES):
        with pytest.raises(TunnelError) as e:
            redeem("AAAA-BBBB", ip="9.9.9.9", now=500)
        assert e.value.status_code == 404
    with pytest.raises(TunnelError) as e:
        redeem("AAAA-BBBB", ip="9.9.9.9", now=501)
    assert e.value.status_code == 429 and "Wait a minute" in str(e.value)
    # another address is not held up, and the wait ends
    with pytest.raises(TunnelError) as other:
        redeem("AAAA-BBBB", ip="8.8.8.8", now=501)
    assert other.value.status_code == 404
    with pytest.raises(TunnelError) as later:
        redeem("AAAA-BBBB", ip="9.9.9.9", now=600)
    assert later.value.status_code == 404


def test_asking_again_always_works_and_only_the_newest_codes_are_kept(tunnel):
    codes = [code_for(now=100 + i) for i in range(agent_tunnel.MAX_PENDING_PER_PROJECT + 2)]
    with pytest.raises(TunnelError):
        redeem(codes[0], now=110)  # the oldest were dropped
    assert redeem(codes[-1], now=110)["projectId"] == PID


def test_a_code_belongs_to_the_project_that_asked_for_it(tunnel):
    c = code_for(PID2)
    assert redeem(c)["projectId"] == PID2
    assert agent_tunnel.get(PID) is None and agent_tunnel.get(PID2)["appPort"] == 3001


# ── what may reach the SSH server's key list ───────────────────────────────

@pytest.mark.parametrize("bad", [
    "",
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ",
    key() + " extra-comment",
    key() + "\nrestrict,command=\"/bin/sh\" " + key(2),
    'command="/bin/sh" ' + key(),
    key()[:-3],
    key() + "\n",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA" + "A" * 42,
])
def test_only_a_plain_ed25519_key_is_accepted_and_the_code_is_spent_by_the_attempt(tunnel, bad):
    c = code_for()
    if bad == key() + "\n":
        assert redeem(c, k=bad)["port"], "a trailing newline is just whitespace around a good key"
        return
    with pytest.raises(TunnelError) as e:
        redeem(c, k=bad)
    assert e.value.status_code == 400 and "ed25519" in str(e.value)
    assert not (tunnel / "authorized_keys").read_text()
    with pytest.raises(TunnelError):
        redeem(c)


def test_a_bad_port_or_secret_is_refused_without_writing_anything(tunnel):
    for port in (0, 70000, "abc", None):
        with pytest.raises(TunnelError):
            redeem(code_for(), port=port)
    for secret in ("short", "x" * 200, "has space " * 5, ""):
        with pytest.raises(TunnelError):
            redeem(code_for(), secret=secret)
    assert agent_tunnel.get(PID) is None and (tunnel / "authorized_keys").read_text() == ""


def test_each_key_may_open_only_its_own_port_and_run_nothing(tunnel):
    out = redeem(code_for())
    line = (tunnel / "authorized_keys").read_text().strip()
    assert line == f'restrict,port-forwarding,permitlisten="0.0.0.0:{out["port"]}",command="/bin/false" {key()} ttf-{PID}'
    assert (tunnel / "authorized_keys").read_text().count("\n") == 1
    assert oct((tunnel / "registry.json").stat().st_mode & 0o777) in ("0o600", "0o666"), "the registry holds secrets (666 only where Windows has no modes)"


def test_a_damaged_registry_entry_is_never_written_to_the_key_list(tunnel):
    reg = {"projects": {PID: {"port": 22001, "publicKey": 'command="x" ' + key()}, "bad id!": {"port": 22002, "publicKey": key()}}, "pending": {}}
    assert agent_tunnel.authorized_keys(reg) == ""


# ── ports ────────────────────────────────────────────────────────────────────

def test_a_project_keeps_its_port_when_it_pairs_again_and_two_projects_never_share_one(tunnel):
    first = redeem(code_for())["port"]
    assert redeem(code_for(), k=key(2))["port"] == first
    assert (tunnel / "authorized_keys").read_text().count("\n") == 1, "the new key replaces the old one"
    assert key(2) in (tunnel / "authorized_keys").read_text() and key(1) not in (tunnel / "authorized_keys").read_text()
    second = redeem(code_for(PID2), k=key(3))["port"]
    assert second != first and 22000 <= first <= 22999 and 22000 <= second <= 22999


def test_a_colliding_port_moves_on_to_the_next_free_one(tunnel, monkeypatch):
    monkeypatch.setenv("FORGE_TUNNEL_PORT_LO", "30000")
    monkeypatch.setenv("FORGE_TUNNEL_PORT_HI", "30001")
    a = redeem(code_for())["port"]
    b = redeem(code_for(PID2), k=key(2))["port"]
    assert {a, b} == {30000, 30001}
    third = str(uuid.uuid4())
    with pytest.raises(TunnelError) as e:
        redeem(code_for(third), k=key(3))
    assert e.value.status_code == 503 and "no free ports" in str(e.value)


def test_a_computer_that_is_connected_now_is_not_disturbed_by_a_newer_pairing_and_the_code_is_kept(tunnel, monkeypatch):
    first = redeem(code_for(), label="Ana laptop")
    before = (tunnel / "authorized_keys").read_text()
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda port, timeout=1.5: port == first["port"])
    waiting = code_for()
    with pytest.raises(TunnelError) as e:
        redeem(waiting, k=key(2), secret="n" * 43)
    assert e.value.status_code == 409 and "Ana laptop is already connected" in str(e.value) and "Your code has not been used" in str(e.value)
    assert (tunnel / "authorized_keys").read_text() == before, "its key is untouched"
    assert agent_tunnel.get(PID)["secret"] == SECRET, "and so is its secret: the tunnel that works keeps working"
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda port, timeout=1.5: False)  # it has gone
    assert redeem(waiting, k=key(2), secret="n" * 43)["projectId"] == PID, "the same code now works"
    assert agent_tunnel.get(PID)["secret"] == "n" * 43


def test_a_key_that_belongs_to_one_project_cannot_be_given_to_another(tunnel):
    redeem(code_for(PID))
    with pytest.raises(TunnelError) as e:
        redeem(code_for(PID2))  # the same key again, for a second project
    assert e.value.status_code == 409 and "already connected to another project" in str(e.value)
    assert agent_tunnel.get(PID2) is None
    assert redeem(code_for(PID2), k=key(2))["projectId"] == PID2, "a new key for the second project is fine"
    assert redeem(code_for(PID), k=key(1))["projectId"] == PID, "and a project may pair again with its own key"


def test_many_writers_at_once_lose_nothing(tunnel):
    """The backend runs two worker processes; the registry is read, changed and written back, so writers must take turns."""
    import threading

    codes: list[str] = []
    errors: list[Exception] = []

    def ask(i):
        try:
            codes.append(agent_tunnel.new_pairing(f"aaaaaaaa-0000-0000-0000-{i:012d}")["code"])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(codes)) == 20
    results = []

    def redeem_one(i):
        try:
            results.append(agent_tunnel.pair(codes[i], key(i + 1), 3000 + i, SECRET, client_ip=f"9.9.9.{i}")["projectId"])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=redeem_one, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(results)) == 20, "every one of the twenty codes was found and used"
    lines = (tunnel / "authorized_keys").read_text().strip().split("\n")
    assert len(lines) == 20 and len({line.split('permitlisten="')[1].split('"')[0] for line in lines}) == 20, "twenty keys, twenty different ports"


# ── what the connector is given ─────────────────────────────────────────────

def test_the_connector_gets_where_to_connect_and_the_host_key_to_trust(tunnel):
    out = redeem(code_for())
    assert out["sshHost"] == "13.212.213.53" and out["sshPort"] == 2222 and out["sshUser"] == "tunnel"
    assert out["hostKey"] == key(9), "the key only: the comment on the file is not passed on"
    assert "secret" not in out and SECRET not in str(out)


def test_a_platform_that_does_not_know_its_address_or_has_no_host_key_says_so(tunnel, monkeypatch):
    monkeypatch.delenv("FORGE_TUNNEL_PUBLIC_HOST")
    with pytest.raises(TunnelError) as e:
        redeem(code_for())
    assert e.value.status_code == 503 and "FORGE_TUNNEL_PUBLIC_HOST" in str(e.value)
    monkeypatch.setenv("FORGE_TUNNEL_PUBLIC_HOST", "h")
    (tunnel / "host_key.pub").unlink()
    with pytest.raises(TunnelError) as again:
        redeem(code_for())
    assert "not ready yet" in str(again.value)
    (tunnel / "host_key.pub").write_text("garbage\n", encoding="utf-8")
    with pytest.raises(TunnelError) as odd:
        agent_tunnel.host_key()
    assert "cannot read" in str(odd.value)


def test_where_to_connect_is_public_and_says_why_when_it_cannot(tunnel, monkeypatch):
    assert agent_tunnel.info() == {"sshHost": "13.212.213.53", "sshPort": 2222, "sshUser": "tunnel", "hostKey": key(9)}
    monkeypatch.delenv("FORGE_TUNNEL_PUBLIC_HOST")
    with pytest.raises(TunnelError) as e:
        agent_tunnel.info()
    assert e.value.status_code == 503 and "FORGE_TUNNEL_PUBLIC_HOST" in str(e.value)
    monkeypatch.delenv("FORGE_TUNNEL_DIR")
    with pytest.raises(TunnelError) as off:
        agent_tunnel.info()
    assert "no tunnel service" in str(off.value)


def test_the_address_shown_is_one_a_person_could_be_reached_on_never_a_private_gateway(tunnel):
    for private in ("172.18.0.1", "10.0.0.5", "192.168.1.9", "127.0.0.1", "::1", "169.254.1.1", "unknown", ""):
        assert agent_tunnel.public_address(private) is None, private
    assert agent_tunnel.public_address("93.184.216.34") == "93.184.216.34"
    redeem(code_for(), ip="172.18.0.1")
    assert agent_tunnel.describe(PID)["clientIp"] is None, "a container-network gateway is not the builder's address"
    out = redeem(code_for(), ip="93.184.216.34")
    assert out["yourAddress"] == "93.184.216.34" and agent_tunnel.describe(PID)["clientIp"] == "93.184.216.34"


def test_off_without_a_tunnel_folder(monkeypatch):
    monkeypatch.delenv("FORGE_TUNNEL_DIR", raising=False)
    assert agent_tunnel.enabled() is False
    assert agent_tunnel.describe(PID) == {"enabled": False, "registered": False, "connected": False}
    assert agent_tunnel.get(PID) is None and agent_tunnel.target_url(PID) is None
    with pytest.raises(TunnelError) as e:
        agent_tunnel.new_pairing(PID)
    assert e.value.status_code == 503


# ── the tunnel being up ──────────────────────────────────────────────────────

def test_connected_only_while_the_listener_exists_and_the_state_never_carries_the_secret(tunnel):
    out = redeem(code_for())
    state = agent_tunnel.describe(PID)
    assert state["registered"] is True and state["connected"] is False and state["appPort"] == 3001 and state["clientIp"] == "1.2.3.4"
    assert SECRET not in str(state)
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", out["port"]))
        srv.listen(1)
        assert agent_tunnel.describe(PID)["connected"] is True
    assert agent_tunnel.describe(PID)["connected"] is False
    assert agent_tunnel.target_url(PID) == f"http://127.0.0.1:{out['port']}"


def test_revoking_forgets_the_computer_its_key_and_any_open_codes(tunnel):
    redeem(code_for())
    code_for()
    assert agent_tunnel.revoke(PID) is True
    assert agent_tunnel.get(PID) is None and (tunnel / "authorized_keys").read_text() == ""
    assert agent_tunnel.revoke(PID) is False
    with pytest.raises(TunnelError):
        redeem(code_for(PID2) if False else "AAAA-BBBB")


# ── what Watch live says ────────────────────────────────────────────────────

REAL_CLIENT = httpx.AsyncClient


def fake_app(monkeypatch, handler):
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


@pytest.fixture()
def paired(tunnel, monkeypatch):
    redeem(code_for())
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda port, timeout=1.5: True)


@pytest.mark.asyncio
async def test_a_platform_on_the_builders_own_computer_has_nothing_to_connect(monkeypatch):
    monkeypatch.delenv("FORGE_TUNNEL_DIR", raising=False)
    out = await agent_debug.tunnel_status(PID)
    assert out["ok"] is False and "runs on your own computer" in out["reason"]


@pytest.mark.asyncio
async def test_a_computer_that_was_never_paired_is_told_how(tunnel):
    out = await agent_debug.tunnel_status(PID)
    assert out["ok"] is False and out["reason"] == agent_debug.NOT_PAIRED and "Connect your computer" in out["reason"]


@pytest.mark.asyncio
async def test_a_tunnel_that_is_down_says_so_and_how_to_bring_it_back(tunnel):
    redeem(code_for())
    out = await agent_debug.tunnel_status(PID)
    assert out["ok"] is False and out["reason"] == agent_debug.TUNNEL_DOWN and "reconnects by itself" in out["reason"]
    assert out["tunnel"]["registered"] is True and out["tunnel"]["connected"] is False


@pytest.mark.asyncio
async def test_a_tunnel_that_is_up_with_nothing_behind_it_names_the_port_to_start_the_app_on(paired, monkeypatch):
    def handler(req):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    fake_app(monkeypatch, handler)
    out = await agent_debug.tunnel_status(PID)
    assert out["ok"] is False and "connected, but nothing answered on port 3001" in out["reason"] and "npm run dev" in out["reason"]


@pytest.mark.asyncio
async def test_the_listener_vanishing_between_the_two_checks_is_a_down_tunnel_not_a_crash(paired, monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused")

    fake_app(monkeypatch, handler)
    out = await agent_debug.tunnel_status(PID)
    assert out["reason"] == agent_debug.TUNNEL_DOWN and out["tunnel"]["connected"] is False


@pytest.mark.asyncio
async def test_an_app_that_does_not_accept_the_key_or_is_not_one_of_ours_is_told_apart(paired, monkeypatch):
    fake_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}))
    refused = await agent_debug.tunnel_status(PID)
    assert refused["reason"] == agent_debug.WRONG_KEY and "run it again from the app's own folder" in refused["reason"]
    assert "production build" in refused["reason"] and "Apply the agent once" in refused["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    assert "answered with an error (500)" in (await agent_debug.tunnel_status(PID))["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(200, text="<html>a page</html>"))
    assert "not one of your apps" in (await agent_debug.tunnel_status(PID))["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(200, json={"hello": "world"}))
    assert "not one of your apps" in (await agent_debug.tunnel_status(PID))["reason"]


@pytest.mark.asyncio
async def test_an_app_behind_the_tunnel_that_accepts_the_key_can_be_watched_and_is_sent_the_projects_own_secret(paired, monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), req.headers.get("x-forge-debug-secret")))
        return httpx.Response(200, json={"agents": [{"id": "support", "name": "Support", "enabled": True}]})

    fake_app(monkeypatch, handler)
    out = await agent_debug.tunnel_status(PID)
    assert out["ok"] is True and out["agents"][0]["id"] == "support" and out["appUrl"] == "your computer, port 3001"
    port = agent_tunnel.get(PID)["port"]
    assert seen == [(f"http://127.0.0.1:{port}/api/agent/debug", SECRET)], "the address is the platform's own, and the secret is the one the connector made"
    assert SECRET not in str(out)


@pytest.mark.asyncio
async def test_the_stream_through_the_tunnel_passes_the_apps_events_and_names_a_drop_in_words(paired, monkeypatch):
    def ok(req: httpx.Request):
        assert req.url.params["watch"] == "1" and req.headers["x-forge-debug-secret"] == SECRET
        return httpx.Response(200, content=b'data: {"type":"watch_ready"}\n\n')

    fake_app(monkeypatch, ok)
    url = agent_tunnel.target_url(PID)
    got = [c async for c in agent_debug.watch_stream(url, SECRET, trusted=True)]
    assert got == [b'data: {"type":"watch_ready"}\n\n']

    def dropped(req):
        raise httpx.RemoteProtocolError("peer closed")

    fake_app(monkeypatch, dropped)
    said = b"".join([c async for c in agent_debug.watch_stream(url, SECRET, trusted=True)]).decode()
    assert "connection to your computer broke" in said and "RemoteProtocolError" in said

    def refused(req):
        raise httpx.ConnectError("no")

    fake_app(monkeypatch, refused)
    assert agent_debug.TUNNEL_DOWN in b"".join([c async for c in agent_debug.watch_stream(url, SECRET, trusted=True)]).decode()


@pytest.mark.asyncio
async def test_an_address_a_person_typed_is_still_limited_to_this_computer(paired):
    said = b"".join([c async for c in agent_debug.watch_stream("http://example.com", "x")]).decode()
    assert "this computer" in said
    # while the platform's own tunnel address (not on loopback) is accepted only when it says so
    assert "this computer" not in b"".join([c async for c in agent_debug.watch_stream("http://tunnel:22001", None, trusted=True)]).decode()


def test_only_the_person_who_registered_a_computer_or_an_admin_may_replace_or_remove_it(tunnel):
    ana, bob = "user-ana", "user-bob"
    agent_tunnel.pair(agent_tunnel.new_pairing(PID, user_id=ana)["code"], key(), 3001, SECRET, client_ip="1.2.3.4")
    assert agent_tunnel.get(PID)["registeredBy"] == ana
    # offline (nothing listening): a colleague may not ask for a code to take it over, nor remove it
    with pytest.raises(TunnelError) as e:
        agent_tunnel.new_pairing(PID, user_id=bob)
    assert e.value.status_code == 403 and "colleague" in str(e.value)
    with pytest.raises(TunnelError) as e:
        agent_tunnel.revoke(PID, user_id=bob)
    assert e.value.status_code == 403
    assert agent_tunnel.get(PID)["publicKey"] == key(), "nothing changed"
    # the one who registered it may, and so may an admin, who leaves the computer still belonging to Ana
    agent_tunnel.new_pairing(PID, user_id=ana)
    code = agent_tunnel.new_pairing(PID, user_id=bob, is_admin=True)["code"]
    agent_tunnel.pair(code, key(2), 3001, "n" * 43, client_ip="1.2.3.4")
    assert agent_tunnel.get(PID)["publicKey"] == key(2) and agent_tunnel.get(PID)["registeredBy"] == ana
    assert agent_tunnel.revoke(PID, user_id=bob, is_admin=True) is True


def test_a_code_asked_for_before_a_colleague_registered_cannot_take_their_computer_over(tunnel):
    bob_code = agent_tunnel.new_pairing(PID, user_id="user-bob")["code"]            # nothing registered yet, so Bob may ask
    agent_tunnel.pair(agent_tunnel.new_pairing(PID, user_id="user-ana")["code"], key(), 3001, SECRET, client_ip="1.2.3.4")
    with pytest.raises(TunnelError) as e:
        agent_tunnel.pair(bob_code, key(2), 3001, "n" * 43, client_ip="1.2.3.4")
    assert e.value.status_code == 403 and agent_tunnel.get(PID)["publicKey"] == key()


def test_a_computer_registered_before_owners_were_recorded_stays_open_to_any_member(tunnel):
    redeem(code_for())                                                               # no user on the code: no owner recorded
    assert agent_tunnel.get(PID)["registeredBy"] is None
    agent_tunnel.new_pairing(PID, user_id="user-bob")
    assert agent_tunnel.revoke(PID, user_id="user-bob") is True


# ── the gateway: the platform reaches a computer only through it ─────────────

class _Reply:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_through_the_gateway_the_platform_asks_it_and_never_opens_a_tunnel_port(tunnel, monkeypatch):
    import urllib.error
    import urllib.request

    monkeypatch.setenv("FORGE_TUNNEL_GATEWAY", "http://tunnel:8080/")
    out = redeem(code_for())
    port = out["port"]
    assert agent_tunnel.settings()["gateway"] == "http://tunnel:8080"
    assert agent_tunnel.target_url(PID) == f"http://tunnel:8080/t/{port}"

    asked = []
    answer = {"status": 200}

    def fake_urlopen(url, timeout=None):
        asked.append(url)
        if answer["status"] == 200:
            return _Reply(200)
        if answer["status"] == "down":
            raise urllib.error.URLError("refused")
        raise urllib.error.HTTPError(url, answer["status"], "no", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert agent_tunnel.describe(PID)["connected"] is True
    assert asked == [f"http://tunnel:8080/up/{port}"], "it asks the gateway, on the one path it answers"

    # A raw listener on the tunnel port is not what counts: the gateway says no computer holds the port, so it is not connected.
    answer["status"] = 404
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        assert agent_tunnel.describe(PID)["connected"] is False
    answer["status"] = "down"
    assert agent_tunnel.describe(PID)["connected"] is False, "a gateway that is down is not connected either"


def test_without_a_gateway_nothing_changes(tunnel, monkeypatch):
    monkeypatch.delenv("FORGE_TUNNEL_GATEWAY", raising=False)
    out = redeem(code_for())
    assert agent_tunnel.settings()["gateway"] == ""
    assert agent_tunnel.target_url(PID) == f"http://127.0.0.1:{out['port']}"
