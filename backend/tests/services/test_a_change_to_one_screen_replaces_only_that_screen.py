"""A change to one screen sent the phone back to the app's first screen (reported 2026-10-22 and again 2026-10-23).

Found with a real browser, on a copy of a built app: tap to the Today tab, edit one word on the Today screen, and 0.4 s later the phone was on the
first tab, no reload. The hot update replaced TWO modules: the screen, and `src/sdk/preview-data` (the sample data). The live preview rewrites that
file whenever its text differs, and every sample date carried the SECOND it was made in, so every change wrote a new file. A data file cannot be
hot-swapped; the update climbs through everything that imports it to the app's root, the navigator is rebuilt, and a rebuilt navigator opens on
its first tab. (A first guess, that Expo Router starts again on the update, was checked and was wrong: it does not.)

Sample dates are counted from today at noon, the same all day, so the file only changes when the data does."""
from datetime import datetime, timedelta, timezone

import pytest

from services import phone_live as pl
from services import phone_preview as pp

DOC = {
    "application": {"name": "PlantPal"},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Plant", "fields": [
        {"name": "name", "type": "text"}, {"name": "lastWatered", "type": "datetime"}, {"name": "waterEveryDays", "type": "integer"}]}]},
    "pages": [{"id": "PAGE-001", "name": "My Plants", "route": "/plants"}],
}


class _Clock(datetime):
    """`datetime` with a clock the test moves."""
    at = datetime(2026, 10, 23, 9, 41, 7, 123456, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.at


@pytest.fixture
def clock(monkeypatch):
    _Clock.at = datetime(2026, 10, 23, 9, 41, 7, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(pp, "datetime", _Clock)
    return _Clock


def test_sample_dates_do_not_change_from_one_second_to_the_next(clock):
    first = pp.sample_data(DOC)
    clock.at += timedelta(seconds=1, milliseconds=300)
    assert pp.sample_data(DOC) == first
    clock.at += timedelta(hours=6)                         # the same day
    assert pp.sample_data(DOC) == first


def test_they_are_counted_from_the_day_so_a_new_day_moves_them_by_a_day(clock):
    assert pp._iso(0) == "2026-10-23T12:00:00Z" and pp._iso(-3) == "2026-10-20T12:00:00Z" and pp._iso(1) == "2026-10-24T12:00:00Z"
    clock.at += timedelta(days=1)
    assert pp._iso(0) == "2026-10-24T12:00:00Z"


def test_a_second_sync_does_not_rewrite_the_sample_data_file(clock, tmp_path):
    """The file is what the dev server watches: writing it again, even with the same meaning, is an update to the app."""
    stage = tmp_path / "stage"
    (stage / "src" / "sdk").mkdir(parents=True)
    assert pl._refresh_sample_data(DOC, stage) == 1, "written the first time"
    target = stage / "src" / "sdk" / "preview-data.json"
    before = target.stat().st_mtime_ns
    for _ in range(3):
        clock.at += timedelta(seconds=2)
        assert pl._refresh_sample_data(DOC, stage) == 0, "nothing changed, so nothing is written"
    assert target.stat().st_mtime_ns == before


def test_the_file_is_written_again_when_the_data_really_changes(clock, tmp_path):
    stage = tmp_path / "stage"
    (stage / "src" / "sdk").mkdir(parents=True)
    pl._refresh_sample_data(DOC, stage)
    more = {**DOC, "data": {"entities": DOC["data"]["entities"] + [{"id": "ENTITY-002", "name": "Room", "fields": [{"name": "label", "type": "text"}]}]}}
    assert pl._refresh_sample_data(more, stage) == 1
