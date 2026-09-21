from pathlib import Path

import pytest

from ufc_scraper.config import Settings
from ufc_scraper.paths import KINDS, cache_path, processed_dir, raw_dir, url_for

S = Settings(data_dir=Path("data"), date="2026-09-21")
ID = "a1b2c3d4e5f60718"


def test_raw_and_processed_dirs():
    assert raw_dir(S) == Path("data/raw/2026-09-21")
    assert processed_dir(S) == Path("data/processed/2026-09-21")


@pytest.mark.parametrize(
    "kind, key, expected",
    [
        ("events_list", None, "data/raw/2026-09-21/events_list.html"),
        ("event", ID, f"data/raw/2026-09-21/events/{ID}.html"),
        ("fight", ID, f"data/raw/2026-09-21/fights/{ID}.html"),
        ("fighter", ID, f"data/raw/2026-09-21/fighters/{ID}.html"),
        ("fighters_list", "a", "data/raw/2026-09-21/fighters_list/a.html"),
    ],
)
def test_cache_path(kind, key, expected):
    assert cache_path(S, kind, key) == Path(expected)


@pytest.mark.parametrize(
    "kind, key, expected",
    [
        ("events_list", None, "http://ufcstats.com/statistics/events/completed?page=all"),
        ("event", ID, f"http://ufcstats.com/event-details/{ID}"),
        ("fight", ID, f"http://ufcstats.com/fight-details/{ID}"),
        ("fighter", ID, f"http://ufcstats.com/fighter-details/{ID}"),
        ("fighters_list", "a", "http://ufcstats.com/statistics/fighters?char=a&page=all"),
    ],
)
def test_url_for(kind, key, expected):
    assert url_for(kind, key) == expected


def test_url_for_custom_base():
    assert url_for("event", ID, base_url="http://localhost:8000") == f"http://localhost:8000/event-details/{ID}"


def test_every_kind_covered():
    # Garante que novos kinds adicionados a paths.py ganhem teste acima.
    assert set(KINDS) == {"events_list", "event", "fight", "fighter", "fighters_list"}


def test_unknown_kind():
    with pytest.raises(ValueError):
        cache_path(S, "bogus", ID)


def test_events_list_rejects_key():
    with pytest.raises(ValueError):
        url_for("events_list", "x")


@pytest.mark.parametrize("kind", ["event", "fight", "fighter", "fighters_list"])
def test_key_required(kind):
    with pytest.raises(ValueError):
        cache_path(S, kind, None)
