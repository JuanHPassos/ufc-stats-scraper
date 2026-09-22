"""Testes do cliente HTTP. Nunca tocam a rede: sessão, sleep e relógio são falsos."""

from __future__ import annotations

import random

import pytest
import requests

from ufc_scraper.config import Settings
from ufc_scraper.http import FetchError, Fetcher, NotFound, fetch, get_fetcher
from ufc_scraper.paths import cache_path

ID = "abc123def4567890"
HTML = b"<html><body>ol\xc3\xa1</body></html>"  # "olá" em UTF-8


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = HTML):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Devolve, em ordem, os itens de `script`: FakeResponse ou exceção a levantar."""

    def __init__(self, script, post_status: int = 204):
        self.script = list(script)
        self.calls: list[str] = []
        self.posts: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}
        self.post_status = post_status

    def get(self, url, timeout):
        self.calls.append(url)
        assert timeout == 30
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, data, timeout):
        self.posts.append((url, data))
        assert timeout == 30
        return FakeResponse(self.post_status, b"")


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, date="2026-09-21")


def make(settings, script, *, seed=0, post_status=204):
    session = FakeSession(script, post_status=post_status)
    sleeps: list[float] = []
    clock = FakeClock()
    f = Fetcher(settings, session=session, sleep=sleeps.append, clock=clock, rng=random.Random(seed))
    return f, session, sleeps, clock


# -- cache --------------------------------------------------------------------


def test_cache_hit_does_not_call_network_or_sleep(settings):
    path = cache_path(settings, "event", ID)
    path.parent.mkdir(parents=True)
    path.write_bytes(HTML)

    f, session, sleeps, _ = make(settings, [])
    assert f.fetch("event", ID) == "<html><body>olá</body></html>"
    assert session.calls == []
    assert sleeps == []
    assert f.stats["cache_hits"] == 1


def test_cache_miss_downloads_writes_then_hits(settings):
    f, session, sleeps, _ = make(settings, [FakeResponse(200)])
    html = f.fetch("event", ID)

    assert html == "<html><body>olá</body></html>"
    assert session.calls == [f"http://ufcstats.com/event-details/{ID}"]
    path = cache_path(settings, "event", ID)
    assert path.read_bytes() == HTML
    assert not path.with_name(path.name + ".tmp").exists()

    assert f.fetch("event", ID) == html  # segunda chamada: cache
    assert len(session.calls) == 1
    assert sleeps == []  # primeira requisição real não espera; cache hit não dorme


def test_force_bypasses_cache(settings):
    f, session, _, _ = make(settings, [FakeResponse(200), FakeResponse(200, b"v2")])
    f.fetch("event", ID)
    assert f.fetch("event", ID, force=True) == "v2"
    assert len(session.calls) == 2


def test_user_agent_is_set_on_session(settings):
    f, session, _, _ = make(settings, [])
    assert session.headers["User-Agent"] == settings.user_agent
    assert "@" in session.headers["User-Agent"]


# -- retry --------------------------------------------------------------------


def test_retry_on_5xx_then_success(settings):
    f, session, sleeps, _ = make(settings, [FakeResponse(500), FakeResponse(500), FakeResponse(200)])
    assert f.fetch("fight", ID) == "<html><body>olá</body></html>"
    assert len(session.calls) == 3
    assert sleeps == [5, 15]
    assert f.stats["retries"] == 2


def test_retry_on_connection_error_and_timeout(settings):
    f, session, sleeps, _ = make(
        settings,
        [requests.ConnectionError("boom"), requests.Timeout("slow"), FakeResponse(200)],
    )
    f.fetch("fight", ID)
    assert len(session.calls) == 3
    assert sleeps == [5, 15]


def test_gives_up_after_max_retries(settings):
    f, session, sleeps, _ = make(settings, [FakeResponse(500)] * 4)
    with pytest.raises(FetchError):
        f.fetch("fight", ID)
    assert len(session.calls) == 4  # 1 + max_retries
    assert sleeps == [5, 15, 45]
    assert not cache_path(settings, "fight", ID).exists()


def test_404_raises_not_found_without_retry(settings):
    f, session, sleeps, _ = make(settings, [FakeResponse(404)])
    with pytest.raises(NotFound):
        f.fetch("fighter", ID)
    assert len(session.calls) == 1
    assert sleeps == []
    assert not cache_path(settings, "fighter", ID).exists()


def test_other_4xx_is_fetch_error_without_retry(settings):
    f, session, _, _ = make(settings, [FakeResponse(403)])
    with pytest.raises(FetchError):
        f.fetch("fighter", ID)
    assert len(session.calls) == 1


def test_not_found_is_not_a_fetch_error():
    # crawl.py trata os dois de forma diferente; garantir que não são subclasses.
    assert not issubclass(NotFound, FetchError)
    assert not issubclass(FetchError, NotFound)


# -- rate limit ---------------------------------------------------------------


def test_rate_limit_between_two_real_requests(settings):
    f, _, sleeps, clock = make(settings, [FakeResponse(200), FakeResponse(200)])
    f.fetch("event", ID)
    f.fetch("event", "ffffffffffffffff")  # relógio parado: precisa esperar o intervalo inteiro
    assert len(sleeps) == 1
    assert settings.delay_min <= sleeps[0] <= settings.delay_max


def test_rate_limit_skips_sleep_when_enough_time_passed(settings):
    f, _, sleeps, clock = make(settings, [FakeResponse(200), FakeResponse(200)])
    f.fetch("event", ID)
    clock.t += 10  # muito mais que delay_max
    f.fetch("event", "ffffffffffffffff")
    assert sleeps == []


def test_rate_limit_uses_configured_interval(tmp_path):
    s = Settings(data_dir=tmp_path, date="2026-09-21", delay_min=3.0, delay_max=4.0)
    f, _, sleeps, _ = make(s, [FakeResponse(200), FakeResponse(200)])
    f.fetch("event", ID)
    f.fetch("event", "ffffffffffffffff")
    assert 3.0 <= sleeps[0] <= 4.0


# -- fachada de módulo --------------------------------------------------------


def test_module_fetch_reuses_fetcher_per_settings(settings, monkeypatch):
    import ufc_scraper.http as http_mod

    monkeypatch.setattr(http_mod, "_default", None)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession([FakeResponse(200)]))
    fetch(settings, "event", ID)
    first = get_fetcher(settings)
    fetch(settings, "event", ID)  # cache hit no mesmo fetcher
    assert get_fetcher(settings) is first
    assert first.stats == {"cache_hits": 1, "requests": 1, "retries": 0, "challenges": 0}


# -- desafio anti-bot ---------------------------------------------------------

# Trecho relevante do script real devolvido pelo site em 2026-09-21.
CHALLENGE = (
    b"<!doctype html><html><head><meta charset=\"utf-8\">\n<title>Loading\xe2\x80\xa6</title>"
    b"</head><body>\n<p>Checking your browser\xe2\x80\xa6</p>\n<script>\n(function(){\n"
    b"function sha256(msg){/* ... */}\n"
    b'var nonce="beda8ba696058bae",\n'
    b"    target=new Array(2+1).join('0');\n"
    b"var n=0;\nwhile(sha256(nonce+':'+n).slice(0,target.length)!==target){n++;}\n"
    b"var xhr=new XMLHttpRequest();\nxhr.open('POST',\"/__c\",true);\n"
    b"xhr.send('nonce='+encodeURIComponent(nonce)+'&n='+n);\n})();\n</script>\n</body></html>"
)


def test_challenge_page_is_detected():
    from ufc_scraper.http import is_challenge_page

    assert is_challenge_page(CHALLENGE)
    assert not is_challenge_page(HTML)
    assert not is_challenge_page(b"<html>Checking your browser settings page</html>")  # só um marcador


def test_parse_and_solve_challenge_matches_site_algorithm():
    import hashlib

    from ufc_scraper.http import parse_challenge, solve_challenge

    nonce, difficulty = parse_challenge(CHALLENGE)
    assert (nonce, difficulty) == ("beda8ba696058bae", 2)
    n = solve_challenge(nonce, difficulty)
    assert hashlib.sha256(f"{nonce}:{n}".encode()).hexdigest().startswith("00")
    # é o menor n possível (o JS incrementa a partir de 0)
    assert all(not hashlib.sha256(f"{nonce}:{m}".encode()).hexdigest().startswith("00") for m in range(n))


def test_parse_challenge_rejects_unknown_script():
    from ufc_scraper.http import parse_challenge

    with pytest.raises(ValueError):
        parse_challenge(b"<html>Checking your browser /__c</html>")
    with pytest.raises(ValueError):
        parse_challenge(b'var nonce="ab"; target=new Array(9+1).join(\'0\')')  # dificuldade absurda


def test_challenge_is_solved_posted_and_page_refetched(settings):
    f, session, sleeps, _ = make(settings, [FakeResponse(200, CHALLENGE), FakeResponse(200)])
    assert f.fetch("events_list") == "<html><body>olá</body></html>"

    assert len(session.calls) == 2  # GET (interstitial) + GET (conteúdo)
    assert len(session.posts) == 1
    post_url, data = session.posts[0]
    assert post_url == "http://ufcstats.com/__c"
    assert data["nonce"] == "beda8ba696058bae" and isinstance(data["n"], int)
    # POST e re-GET respeitam o rate limit (relógio parado => 2 esperas no intervalo)
    assert len(sleeps) == 2 and all(settings.delay_min <= x <= settings.delay_max for x in sleeps)
    assert f.stats == {"cache_hits": 0, "requests": 3, "retries": 0, "challenges": 1}
    assert cache_path(settings, "events_list").read_bytes() == HTML


def test_challenge_page_is_never_cached_when_it_persists(settings):
    from ufc_scraper.http import ChallengeRequired

    f, session, _, _ = make(settings, [FakeResponse(200, CHALLENGE), FakeResponse(200, CHALLENGE)])
    with pytest.raises(ChallengeRequired):
        f.fetch("events_list")
    assert len(session.calls) == 2 and len(session.posts) == 1  # não entra em loop
    assert not cache_path(settings, "events_list").exists()


def test_challenge_post_failure_raises(settings):
    from ufc_scraper.http import ChallengeRequired

    f, session, _, _ = make(settings, [FakeResponse(200, CHALLENGE)], post_status=403)
    with pytest.raises(ChallengeRequired):
        f.fetch("events_list")
    assert len(session.calls) == 1
    assert not cache_path(settings, "events_list").exists()
