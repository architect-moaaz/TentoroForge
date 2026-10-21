"""A page trial takes one of a few slots, and does so on Windows (no `fcntl`) as well as everywhere else."""
from __future__ import annotations

import sys

import pytest

from services import dev_servers


@pytest.fixture(autouse=True)
def slot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_servers, "DIR", tmp_path)


def test_a_held_slot_is_not_given_to_a_second_trial_and_is_given_again_when_let_go():
    first, second = dev_servers.TrialSlot(wait_s=0.2, slots=1), dev_servers.TrialSlot(wait_s=0.2, slots=1)
    assert first.acquire() == 0
    with pytest.raises(dev_servers.SlotUnavailable):
        second.acquire()
    first.release()
    assert second.acquire() == 0
    second.release()


def test_two_slots_serve_two_trials_and_no_more():
    held = [dev_servers.TrialSlot(wait_s=0.2, slots=2) for _ in range(3)]
    assert sorted([held[0].acquire(), held[1].acquire()]) == [0, 1]
    with pytest.raises(dev_servers.SlotUnavailable):
        held[2].acquire()
    for slot in held[:2]:
        slot.release()


def test_without_fcntl_the_slot_still_works(monkeypatch):
    monkeypatch.setitem(sys.modules, "fcntl", None)          # `import fcntl` now raises ImportError, as on Windows
    if sys.platform != "win32":
        pytest.skip("the msvcrt fallback exists only on Windows")
    slot = dev_servers.TrialSlot(wait_s=0.2, slots=1)
    assert slot.acquire() == 0
    slot.release()
