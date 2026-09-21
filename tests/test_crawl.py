"""Testes do crawler com um Fetcher falso que serve fixtures. Sem rede."""

from __future__ import annotations

import pytest

from ufc_scraper.config import Settings
from ufc_scraper.crawl import FAILURES_FILE, run_crawl
from ufc_scraper.http import ChallengeRequired, FetchError, NotFound
from ufc_scraper.paths import processed_dir

EVENT = "8a0a35e7c74bebcc"
FIGHT_A, FIGHT_B = "568ec6af4008355a", "fe612d20eec7ef35"
VAN, PANTOJA = "17e97649403ba428", "a0f0004aadf10b71"


class FakeFetcher:
    """Serve HTML mínimo por (kind, key); registra a ordem das chamadas."""

    def __init__(self, pages: dict, errors: dict | None = None):
        self.pages = pages
        self.errors = errors or {}
        self.calls: list[tuple[str, str | None]] = []
        self.stats = {"cache_hits": 0, "requests": 0, "retries": 0, "challenges": 0}

    def fetch(self, kind, key=None, *, force=False):
        self.calls.append((kind, key))
        if (kind, key) in self.errors:
            raise self.errors[(kind, key)]
        self.stats["requests"] += 1
        return self.pages[(kind, key)]


def link(kind: str, ids: list[str]) -> str:
    return "".join(f'<a href="http://ufcstats.com/{kind}-details/{i}">x</a>' for i in ids)


def small_site() -> dict:
    """Lista com 1 evento; evento com 2 lutas; Van luta nas duas (dedupe)."""
    return {
        ("events_list", None): "<table><tr>" + link("event", [EVENT]) + "</tr></table>",
        ("event", EVENT): link("fight", [FIGHT_A, FIGHT_B]) + link("fighter", [VAN, PANTOJA]),
        ("fight", FIGHT_A): link("fighter", [VAN, PANTOJA]),
        ("fight", FIGHT_B): link("fighter", [VAN, "cccccccccccccccc"]),
        ("fighter", VAN): "<html/>",
        ("fighter", PANTOJA): "<html/>",
        ("fighter", "cccccccccccccccc"): "<html/>",
        **{("fighters_list", c): "" for c in "abcdefghijklmnopqrstuvwxyz"},
        ("fighters_list", "z"): link("fighter", ["dddddddddddddddd", VAN]),
        ("fighter", "dddddddddddddddd"): "<html/>",
    }


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, date="2026-09-21")


def test_full_crawl_order_and_dedupe(settings):
    f = FakeFetcher(small_site())
    report = run_crawl(settings, fetcher=f)

    kinds = [k for k, _ in f.calls]
    # ordem: lista -> evento -> lutas -> listas A-Z -> lutadores
    assert kinds[:4] == ["events_list", "event", "fight", "fight"]
    assert kinds[4:30] == ["fighters_list"] * 26
    assert kinds[30:] == ["fighter"] * 4

    fighters = [k for kind, k in f.calls if kind == "fighter"]
    assert fighters == [VAN, PANTOJA, "cccccccccccccccc", "dddddddddddddddd"]  # únicos, ordem de descoberta
    assert (report.events, report.fights, report.fighters, report.fighters_lists) == (1, 2, 4, 26)
    assert report.failed == 0 and report.not_found == 0


def test_limit_skips_az_list(settings):
    pages = small_site()
    pages[("events_list", None)] = "<table><tr>" + link("event", [EVENT, "eeeeeeeeeeeeeeee"]) + "</tr></table>"
    f = FakeFetcher(pages)
    report = run_crawl(settings, limit=1, fetcher=f)

    assert ("event", "eeeeeeeeeeeeeeee") not in f.calls
    assert not any(k == "fighters_list" for k, _ in f.calls)
    assert report.events == 1 and report.fighters == 3  # dddd… só vinha da lista A-Z


def test_events_list_skips_next_event(settings, fixture):
    pages = small_site()
    pages[("events_list", None)] = fixture("events_list.html")
    f = FakeFetcher(pages)
    with pytest.raises(KeyError):  # segundo evento da lista não está no site falso: prova que o 1º foi o certo
        run_crawl(settings, fetcher=f)
    assert f.calls[1] == ("event", EVENT)
    assert ("event", "7e654edcddd71550") not in f.calls


def test_not_found_and_fetch_error_are_recorded_and_crawl_continues(settings):
    errors = {
        ("fight", FIGHT_A): NotFound("u", "404"),
        ("fighter", PANTOJA): FetchError("u", "falhou"),
    }
    f = FakeFetcher(small_site(), errors)
    report = run_crawl(settings, fetcher=f)

    assert report.fights == 1 and report.not_found == 1 and report.failed == 1
    assert report.fighters == 3
    lines = (processed_dir(settings) / FAILURES_FILE).read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"fight\t{FIGHT_A}\thttp://ufcstats.com/fight-details/{FIGHT_A}\t404")
    assert lines[1].startswith(f"fighter\t{PANTOJA}\t")


def test_challenge_required_aborts(settings):
    f = FakeFetcher(small_site(), {("fight", FIGHT_A): ChallengeRequired("u", "persistiu")})
    with pytest.raises(ChallengeRequired):
        run_crawl(settings, fetcher=f)
    assert not (processed_dir(settings) / FAILURES_FILE).exists()


def test_cli_crawl_exit_codes(settings, monkeypatch):
    import ufc_scraper.__main__ as cli
    import ufc_scraper.crawl as crawl_mod

    monkeypatch.setattr(crawl_mod, "get_fetcher", lambda s: FakeFetcher(small_site()))
    argv = ["crawl", "--date", "2026-09-21", "--data-dir", str(settings.data_dir), "--limit", "1"]
    assert cli.main(argv) == 0

    monkeypatch.setattr(
        crawl_mod, "get_fetcher", lambda s: FakeFetcher(small_site(), {("fighter", VAN): FetchError("u", "x")})
    )
    assert cli.main(argv) == 1
