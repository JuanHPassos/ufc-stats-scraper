import argparse
from pathlib import Path

import pytest

from ufc_scraper.config import Settings, settings_from_args


def test_defaults():
    s = Settings()
    assert s.base_url == "http://ufcstats.com"
    assert s.data_dir == Path("data")
    assert s.mode == "full"
    assert s.backoff == (5, 15, 45)
    assert "@" in s.user_agent  # contato do grupo, spec §6


def test_invalid_date():
    with pytest.raises(ValueError):
        Settings(date="21/09/2026")


def test_invalid_mode():
    with pytest.raises(ValueError):
        Settings(mode="turbo")


def test_delay_order():
    with pytest.raises(ValueError):
        Settings(delay_min=3, delay_max=1)


def test_settings_from_args_only_overrides_present_fields():
    ns = argparse.Namespace(date="2026-09-21", data_dir="/tmp/x", delay_min=None, mode=None)
    s = settings_from_args(ns)
    assert s.date == "2026-09-21"
    assert s.data_dir == Path("/tmp/x")
    assert s.delay_min == 1.0
    assert s.mode == "full"
