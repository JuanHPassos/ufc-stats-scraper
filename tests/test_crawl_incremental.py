"""Modo incremental: base em raw/<base>/, nova pasta raw/<date>/. Fetcher real + sessão falsa; sem rede."""

from __future__ import annotations

import json
import os
import random

import pytest

from ufc_scraper.config import Settings
from ufc_scraper.crawl import latest_base, run_incremental
from ufc_scraper.http import Fetcher
from ufc_scraper.paths import cache_path, raw_dir, url_for

BASE, NEW = "2026-09-21", "2026-10-05"
EV_OLD, EV_NEW = "a" * 16, "b" * 16
F_OLD1, F_OLD2, F_NEW = "1" * 16, "2" * 16, "3" * 16
VET, ROOKIE, OTHER, LISTED = "c" * 16, "d" * 16, "e" * 16, "f" * 16  # VET luta no evento novo; OTHER só na base


def link(kind, ids):
    return "".join(f'<a href="http://ufcstats.com/{kind}-details/{i}">x</a>' for i in ids)


class Resp:
    def __init__(self, content: bytes, status=200):
        self.status_code, self.content = status, content


class UrlSession:
    """GET por URL; registra a ordem. POST não é usado (sem desafio)."""

    def __init__(self, pages: dict[str, str]):
        self.pages, self.calls, self.headers = pages, [], {}

    def get(self, url, timeout):
        self.calls.append(url)
        if url not in self.pages:
            return Resp(b"", 404)
        return Resp(self.pages[url].encode())


def site(new_event: bool, vet_record="10-0-0"):
    """Site falso. Com `new_event`, a lista tem EV_NEW (com F_NEW entre VET e ROOKIE)."""
    events = [EV_NEW, EV_OLD] if new_event else [EV_OLD]
    pages = {
        url_for("events_list"): "<table><tr>" + link("event", events) + "</tr></table>",
        url_for("event", EV_NEW): link("fight", [F_NEW]) + link("fighter", [VET, ROOKIE]),
        url_for("fight", F_NEW): link("fighter", [VET, ROOKIE]),
        url_for("fighter", VET): f"<html>vet {vet_record}</html>",
        url_for("fighter", ROOKIE): "<html>rookie</html>",
        url_for("fighter", LISTED): "<html>listed only</html>",
        **{url_for("fighters_list", c): "" for c in "abcdefghijklmnopqrstuvwxyz"},
        url_for("fighters_list", "z"): link("fighter", [VET, OTHER, LISTED]),
    }
    return pages


@pytest.fixture
def base(tmp_path):
    """Coleta-base já feita: EV_OLD com 2 lutas; perfis de VET e OTHER; lista A-Z antiga."""
    s = Settings(data_dir=tmp_path, date=BASE)
    files = {
        ("events_list", None): "<table><tr>" + link("event", [EV_OLD]) + "</tr></table>",
        ("event", EV_OLD): link("fight", [F_OLD1, F_OLD2]) + link("fighter", [VET, OTHER]),
        ("fight", F_OLD1): link("fighter", [VET, OTHER]),
        ("fight", F_OLD2): link("fighter", [OTHER, VET]),
        ("fighter", VET): "<html>vet 9-0-0</html>",
        ("fighter", OTHER): "<html>other</html>",
        ("fighters_list", "z"): link("fighter", [VET, OTHER]),
    }
    for (kind, key), html in files.items():
        p = cache_path(s, kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    return s


def make_fetcher(settings, pages):
    session = UrlSession(pages)
    f = Fetcher(settings, session=session, sleep=lambda _: None, clock=lambda: 0.0, rng=random.Random(0))
    return f, session


def test_incremental_downloads_only_what_changed(base):
    new = Settings(data_dir=base.data_dir, date=NEW)
    f, session = make_fetcher(new, site(new_event=True))
    report = run_incremental(new, BASE, fetcher=f)

    fetched = set(session.calls)
    # baixados: lista, evento novo, luta nova, 26 listas A-Z, VET (renovado), ROOKIE e LISTED (inéditos)
    assert url_for("events_list") in fetched
    assert url_for("event", EV_NEW) in fetched and url_for("fight", F_NEW) in fetched
    assert {url_for("fighter", x) for x in (VET, ROOKIE, LISTED)} <= fetched
    # NÃO baixados: evento/lutas antigas e OTHER (não envolvido)
    assert url_for("event", EV_OLD) not in fetched
    assert url_for("fight", F_OLD1) not in fetched and url_for("fighter", OTHER) not in fetched
    assert len(session.calls) == 1 + 1 + 1 + 26 + 3
    assert (report.new_events, report.events, report.fights, report.fighters, report.refreshed_fighters) == (1, 1, 1, 3, 1)
    assert report.failed == 0 and report.not_found == 0


def test_incremental_new_folder_is_complete_and_base_untouched(base):
    new = Settings(data_dir=base.data_dir, date=NEW)
    f, _ = make_fetcher(new, site(new_event=True))
    report = run_incremental(new, BASE, fetcher=f)

    # tudo da base presente na nova pasta (copiado), mais o novo
    for kind, key in [("event", EV_OLD), ("fight", F_OLD1), ("fight", F_OLD2), ("fighter", OTHER),
                      ("event", EV_NEW), ("fight", F_NEW), ("fighter", ROOKIE), ("fighter", LISTED)]:
        assert cache_path(new, kind, key).exists(), (kind, key)
    assert report.copied == 4  # EV_OLD, F_OLD1, F_OLD2, OTHER (VET foi renovado, não copiado)
    # perfil renovado tem o conteúdo novo; a base continua com o antigo
    assert "10-0-0" in cache_path(new, "fighter", VET).read_text()
    assert "9-0-0" in cache_path(base, "fighter", VET).read_text()
    # lista de eventos e A-Z são as novas, não cópias
    assert EV_NEW in cache_path(new, "events_list").read_text()
    assert LISTED in cache_path(new, "fighters_list", "z").read_text()
    # cópia por hard link quando possível (mesmo inode)
    assert os.path.samefile(cache_path(new, "fight", F_OLD1), cache_path(base, "fight", F_OLD1))

    manifest = json.loads((raw_dir(new) / "manifest.json").read_text())
    assert manifest["base_date"] == BASE and manifest["new_event_ids"] == [EV_NEW]
    assert set(manifest["fighters_fetched"]) == {VET, ROOKIE, LISTED} and manifest["copied_files"] == 4


def test_incremental_without_new_events_only_lists_and_new_listed_fighters(base):
    new = Settings(data_dir=base.data_dir, date=NEW)
    f, session = make_fetcher(new, site(new_event=False))
    report = run_incremental(new, BASE, fetcher=f)
    assert report.new_events == 0 and report.events == 0
    assert len(session.calls) == 1 + 26 + 1  # lista, A-Z, LISTED (inédito na lista)
    assert report.copied == 5  # EV_OLD, 2 lutas, VET, OTHER


def test_incremental_is_resumable(base):
    """2ª execução: nada baixa de novo (cache), cópias puladas, perfil renovado não volta a ser cópia."""
    new = Settings(data_dir=base.data_dir, date=NEW)
    pages = site(new_event=True)
    f, session = make_fetcher(new, pages)
    run_incremental(new, BASE, fetcher=f)
    first = len(session.calls)

    f2, session2 = make_fetcher(new, pages)
    report = run_incremental(new, BASE, fetcher=f2)
    assert session2.calls == []  # tudo cache hit
    assert report.copied == 0
    assert "10-0-0" in cache_path(new, "fighter", VET).read_text()
    assert first == 32


def test_incremental_refreshes_profile_that_was_only_copied(base):
    """Simula: cópia da base feita, mas o perfil de um envolvido ainda não foi renovado -> force."""
    new = Settings(data_dir=base.data_dir, date=NEW)
    # pré-copia o perfil antigo de VET para a pasta nova (como se uma execução anterior tivesse copiado)
    dst = cache_path(new, "fighter", VET)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.link(cache_path(base, "fighter", VET), dst)
    f, session = make_fetcher(new, site(new_event=True))
    run_incremental(new, BASE, fetcher=f)
    assert url_for("fighter", VET) in session.calls  # forçou o download
    assert "10-0-0" in dst.read_text() and "9-0-0" in cache_path(base, "fighter", VET).read_text()


def test_incremental_errors(base, tmp_path):
    new = Settings(data_dir=base.data_dir, date=NEW)
    f, _ = make_fetcher(new, site(new_event=True))
    with pytest.raises(ValueError):
        run_incremental(new, NEW, fetcher=f)  # base == date
    with pytest.raises(FileNotFoundError):
        run_incremental(new, "2020-01-01", fetcher=f)  # base inexistente


def test_incremental_404_profile_is_recorded_and_continues(base):
    new = Settings(data_dir=base.data_dir, date=NEW)
    pages = site(new_event=True)
    del pages[url_for("fighter", ROOKIE)]
    f, _ = make_fetcher(new, pages)
    report = run_incremental(new, BASE, fetcher=f)
    assert report.not_found == 1 and report.fighters == 2
    assert (new.data_dir / "processed" / NEW / "crawl_failures.txt").read_text().startswith(f"fighter\t{ROOKIE}")


def test_latest_base(tmp_path):
    s = Settings(data_dir=tmp_path, date="2026-12-01")
    assert latest_base(s) is None
    for d in ("2026-09-21", "2026-11-15", "2026-12-01"):
        (tmp_path / "raw" / d / "events").mkdir(parents=True)
    (tmp_path / "raw" / "2026-11-30").mkdir()  # sem events/: não conta
    assert latest_base(s) == "2026-11-15"


def test_cli_incremental(base, monkeypatch):
    import ufc_scraper.__main__ as cli
    import ufc_scraper.crawl as crawl_mod

    pages = site(new_event=True)
    monkeypatch.setattr(crawl_mod, "get_fetcher", lambda s: make_fetcher(s, pages)[0])
    argv = ["crawl", "--mode", "incremental", "--date", NEW, "--data-dir", str(base.data_dir)]
    assert cli.main(argv) == 0  # --base-date omitido: usa a mais recente (BASE)
    assert (raw_dir(Settings(data_dir=base.data_dir, date=NEW)) / "manifest.json").exists()
    assert cli.main(argv + ["--base-date", "2020-01-01"]) == 1
    assert cli.main(["crawl", "--mode", "incremental", "--date", "2030-01-01", "--data-dir", str(base.data_dir / "vazio")]) == 1
