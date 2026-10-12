"""The Researcher studies a reference app in the background (2026-10-08).

Smith briefs it; a scout maps the app's surfaces, workers study each side by
side, a synthesis joins what they found into one dossier. These hold the
dossier's merge, the job on disk, a whole study driven by a stand-in model,
and Smith's two tools for it.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from services.brain_juice import agent, dossier, researcher, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "bj")


def test_two_workers_recording_the_same_screen_add_to_it():
    d, _ = dossier.merge(dossier.empty(), {"screens": [{"name": "Product page", "shows": ["price"]}]})
    d, _ = dossier.merge(d, {"screens": [{"name": "product page", "shows": ["price", "sizes"], "shot": "abc"}],
                             "look": {"fonts": ["Assistant"]}})
    d, _ = dossier.merge(d, {"look": {"fonts": ["Assistant", "Whitney"], "mood": "bold"}})
    assert d["screens"] == [{"name": "Product page", "shows": ["price", "sizes"], "shot": "abc"}]
    assert d["look"] == {"fonts": ["Assistant", "Whitney"], "mood": "bold"}


def test_a_study_keeps_its_own_files_and_a_silent_one_is_stopped():
    s = store.create("org", "u", "")
    job = store.new_job(s["id"], "Example Shop")
    meta = store.add_job_file(job, b"\x89PNG\r\n\x1a\n" + b"0" * 10, name="home", media_type="image/png")
    store.save_job(job)
    assert store.file_meta(s, meta["id"])["job"] == job["id"], "a study's screenshot is the session's to show"
    assert store.file_path(s, meta["id"]).read_bytes().startswith(b"\x89PNG")
    job["heartbeat"] = time.time() - store.STALE_AFTER - 5
    store.save_job(job)
    assert store.load_job(s["id"], job["id"])["status"] == "stopped"


# --------------------------------------------------------------------------- #
# A whole study, with a stand-in model
# --------------------------------------------------------------------------- #

class _Msg:
    def __init__(self, content, stop):
        self._content, self.stop_reason = content, stop
        self.usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0, server_tool_use=None)

    def to_dict(self, mode="json"):
        return {"content": self._content}


def _use(name, args, i=1):
    return {"type": "tool_use", "id": f"{name}-{i}", "name": name, "input": args}


def _stand_in(fail_surface: str | None = None):
    """Answers by stage, told apart by the system prompt it is sent."""
    def create(**kw):
        system = kw["system"][0]["text"]
        last = kw["messages"][-1]
        answered = isinstance(last["content"], list) and last["content"] and last["content"][0].get("type") == "tool_result"
        if "SCOUT" in system:
            if answered:
                return _Msg([{"type": "text", "text": "Mapped."}], "end_turn")
            return _Msg([_use("record", {"product": {"name": "Example Shop", "what": "a clothing store"},
                                         "surfaces": [{"name": "Website", "url": "https://shop.example"}]}),
                         _use("plan", {"surfaces": [{"name": "Website", "look_for": "screens"},
                                                    {"name": "Help centre", "look_for": "rules"}]}, 2)],
                        "tool_use")
        if "joined what they found" in system:
            if answered:
                return _Msg([{"type": "text", "text": "A clothing store; learn its filters."}], "end_turn")
            return _Msg([_use("record", {"roles": [{"name": "Shopper"}],
                                         "flows": [{"name": "Buy", "steps": [{"screen": "Home"}, {"screen": "Bag"}]}]})],
                        "tool_use")
        if isinstance(last["content"], str) and fail_surface \
                and f"Your surface: {fail_surface}" in last["content"]:
            raise RuntimeError("the surface broke")
        if answered:
            return _Msg([{"type": "text", "text": "Studied."}], "end_turn")
        if isinstance(last["content"], str) and "Your surface: Help centre" in last["content"]:
            return _Msg([_use("record", {"rules": [{"text": "Returns within 14 days", "source": "https://shop.example/help"}]})],
                        "tool_use")
        return _Msg([{"type": "server_tool_use", "id": "s", "name": "web_search", "input": {"query": "example shop"}},
                     _use("record", {"screens": [{"name": "Home"}, {"name": "Bag"}],
                                     "features": [{"name": "Filters", "source": "https://shop.example"}]})],
                    "tool_use")
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_a_study_scouts_studies_each_surface_and_joins_them(monkeypatch):
    monkeypatch.setattr(researcher, "_client", lambda: _stand_in())
    s = store.create("org", "u", "")
    job = store.new_job(s["id"], "Example Shop")
    researcher.run(s["id"], job["id"], said=["Example Shop"])
    done = store.load_job(s["id"], job["id"])
    assert done["status"] == "done" and done["summary"] == "A clothing store; learn its filters."
    assert [x["name"] for x in done["surfaces"]] == ["Website", "Help centre"]
    d = done["dossier"]
    assert {x["name"] for x in d["screens"]} == {"Home", "Bag"} and d["rules"][0]["text"].startswith("Returns")
    assert d["roles"] == [{"name": "Shopper"}] and d["flows"][0]["name"] == "Buy"
    assert any("searched" in st["text"] for st in done["steps"]), "the person sees what it is doing"


def test_a_surface_that_fails_is_a_gap_not_a_failed_study(monkeypatch):
    monkeypatch.setattr(researcher, "_client", lambda: _stand_in(fail_surface="Help centre"))
    s = store.create("org", "u", "")
    job = store.new_job(s["id"], "Example Shop")
    researcher.run(s["id"], job["id"], said=[])
    done = store.load_job(s["id"], job["id"])
    assert done["status"] == "done"
    assert any("Help centre could not be studied" in g["text"] for g in done["dossier"]["gaps"])


# --------------------------------------------------------------------------- #
# Smith's side
# --------------------------------------------------------------------------- #

def test_smith_starts_a_study_and_reads_it_once_done(monkeypatch):
    started = []
    monkeypatch.setattr(researcher.threading, "Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: started.append(args)))
    s = store.create("org", "u", "")
    events = []
    out, err = agent.research(s, {"reference": "Example Shop", "focus": "filters"}, lambda e, d: events.append(e))
    assert not err and started and "research" in events
    jid = started[0][1]
    assert "running" in agent.research_status(s)

    out, _ = agent.read_research(s, {"study": jid}, lambda e, d: None)
    assert "Still running" in out[0]["text"]

    job = store.load_job(s["id"], jid)
    job.update(status="done", summary="A store.", dossier=dossier.merge(dossier.empty(), {"screens": [{"name": "Home"}]})[0])
    store.save_job(job)
    assert "not read yet" in agent.research_status(s)
    out, _ = agent.read_research(s, {"study": jid}, lambda e, d: None)
    assert "A store." in out[0]["text"] and '"Home"' in out[0]["text"]
    assert store.load_job(s["id"], jid)["read"] is True
    assert "not read yet" not in agent.research_status(s)


def test_no_more_than_two_studies_at_once(monkeypatch):
    monkeypatch.setattr(researcher.threading, "Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: None))
    s = store.create("org", "u", "")
    for name in ("A", "B"):
        assert not agent.research(s, {"reference": name}, lambda e, d: None)[1]
    out, err = agent.research(s, {"reference": "C"}, lambda e, d: None)
    assert err and "already running" in out[0]["text"]


def test_the_researchers_tasks_name_no_application():
    import re
    for text in (researcher.SCOUT, researcher.STUDY, researcher.SYNTHESISE):
        for brand in ("myntra", "amazon", "zara", "airbnb", "uber", "shopify", "strava"):
            assert not re.search(rf"\b{brand}\b", text.lower()), brand


def test_the_pictures_on_a_page_are_kept_and_looked_at(monkeypatch):
    """When an app's own site turns browsers away, its store listing still
    shows its screens: they are kept with the study and shown to the worker."""
    from services.smith import web
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 9000
    monkeypatch.setattr(web, "_in_thread", lambda fn, *a: (200, [
        {"data": png, "media_type": "image/png", "alt": "Home screen", "src": "https://img.example/1.png", "size": "600w"}]))
    monkeypatch.setattr(web, "check_url", lambda url, said: url)
    s = store.create("org", "u", "")
    job = store.new_job(s["id"], "Example Shop")
    study = researcher.Study(job, said=["shop.example"])
    budget = [1]
    out = study.page_images({"url": "https://store.example/app"}, budget)
    assert out[0]["type"] == "text" and out[1]["type"] == "image", "the worker sees the pictures it collected"
    assert job["files"][0]["caption"] == "Home screen" and budget == [0]
    assert store.file_meta(s, job["files"][0]["id"])["job"] == job["id"]
    assert "No more pages" in study.page_images({"url": "https://store.example/app"}, budget)


def test_a_page_two_workers_reach_is_collected_once(monkeypatch):
    from services.smith import web
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 9000
    calls = []
    def fake(fn, *a):
        calls.append(a)
        return 200, [{"data": png, "media_type": "image/png", "alt": "", "src": "https://img.example/1.png", "size": "600w"}]
    monkeypatch.setattr(web, "_in_thread", fake)
    monkeypatch.setattr(web, "check_url", lambda url, said: url)
    s = store.create("org", "u", "")
    study = researcher.Study(store.new_job(s["id"], "Example Shop"), said=[])
    study.page_images({"url": "https://store.example/app"}, [2])
    again = study.page_images({"url": "https://store.example/app"}, [2])
    assert len(calls) == 1 and "already collected" in again and len(study.job["files"]) == 1
    assert "already kept" in study.page_images({"url": "https://store.example/other"}, [2]), \
        "the same picture reached from another page is not kept twice"
