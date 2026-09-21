"""Cliente HTTP com cache em disco, rate limit e retry (spec §6).

Toda a coleta passa por `fetch(settings, kind, key)`:

- cache hit  -> lê `cache_path(...)` e devolve; sem rede, sem sleep;
- cache miss -> espera o intervalo (1–2 s desde a última requisição real),
  faz GET com User-Agent identificável e timeout, faz retry em 5xx/429 e erros
  de conexão com esperas crescentes (5, 15, 45 s), grava atomicamente e devolve.

404 não faz retry: levanta `NotFound` e o chamador decide o que fazer.
O arquivo é gravado como bytes crus (HTML bruto); a leitura decodifica em UTF-8.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Callable

import requests

from .config import Settings
from .paths import cache_path, url_for

log = logging.getLogger(__name__)

ENCODING = "utf-8"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Marcas da página de desafio anti-bot observada em 2026-09-21 (ver plano, Parte 1).
CHALLENGE_MARKERS = (b"Checking your browser", b"/__c")


class HttpError(Exception):
    """Base dos erros de coleta."""

    def __init__(self, url: str, message: str):
        super().__init__(f"{message} ({url})")
        self.url = url


class FetchError(HttpError):
    """Falha definitiva depois de esgotar as tentativas, ou status não recuperável."""


class NotFound(HttpError):
    """A página não existe (404). Nunca faz retry."""


class ChallengeRequired(HttpError):
    """O site devolveu a página interstitial "Checking your browser…" (desafio
    proof-of-work em JavaScript) em vez do conteúdo. Nunca é gravada no cache.
    """


class Fetcher:
    """Estado compartilhado entre requisições: sessão HTTP e timestamp do rate limit.

    `session`, `sleep` e `clock` são injetáveis para os testes.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = settings.user_agent
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()
        self._last_request: float | None = None
        self.stats = {"cache_hits": 0, "requests": 0, "retries": 0}

    # -- API pública ----------------------------------------------------------

    def fetch(self, kind: str, key: str | None = None, *, force: bool = False) -> str:
        path = cache_path(self.settings, kind, key)
        url = url_for(kind, key, base_url=self.settings.base_url)

        if path.exists() and not force:
            self.stats["cache_hits"] += 1
            log.debug("cache hit %s", path)
            return path.read_text(encoding=ENCODING, errors="replace")

        content = self._download(url)
        _atomic_write(path, content)
        return content.decode(ENCODING, errors="replace")

    # -- internos -------------------------------------------------------------

    def _download(self, url: str) -> bytes:
        s = self.settings
        attempts = s.max_retries + 1
        self._wait_rate_limit()

        for attempt in range(attempts):
            if attempt > 0:
                wait = s.backoff[min(attempt - 1, len(s.backoff) - 1)]
                self.stats["retries"] += 1
                log.warning("retry %d/%d em %ds: %s", attempt, s.max_retries, wait, url)
                self._sleep(wait)

            try:
                content = self._request(url)
            except _Retryable as exc:
                log.warning("%s: %s", exc, url)
                continue
            return content

        raise FetchError(url, f"falhou após {attempts} tentativas")

    def _request(self, url: str) -> bytes:
        """Uma tentativa. Levanta `_Retryable` quando vale tentar de novo."""
        s = self.settings
        t0 = self._clock()
        self.stats["requests"] += 1
        try:
            resp = self.session.get(url, timeout=s.timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise _Retryable(type(exc).__name__) from exc
        finally:
            self._last_request = self._clock()
            elapsed_ms = int((self._last_request - t0) * 1000)

        status = resp.status_code
        log.info("GET %s -> %d (%d ms)", url, status, elapsed_ms)

        if status == 200:
            if is_challenge_page(resp.content):
                raise ChallengeRequired(url, "página de desafio anti-bot em vez do conteúdo")
            return resp.content
        if status == 404:
            raise NotFound(url, "404")
        if status in RETRYABLE_STATUS:
            raise _Retryable(f"status {status}")
        raise FetchError(url, f"status {status}")

    def _wait_rate_limit(self) -> None:
        """Garante `delay_min..delay_max` segundos desde a última requisição real.

        Só é chamada uma vez por `fetch` (antes da primeira tentativa); entre
        retries a espera é o backoff, que já é maior que o intervalo.
        """
        if self._last_request is None:
            return
        s = self.settings
        delay = self._rng.uniform(s.delay_min, s.delay_max)
        remaining = self._last_request + delay - self._clock()
        if remaining > 0:
            self._sleep(remaining)


def is_challenge_page(content: bytes) -> bool:
    """True se o corpo é a interstitial de desafio, não a página pedida.

    Checa só o início do corpo: a interstitial tem ~3 KB e as páginas reais
    têm dezenas de KB, então o custo é desprezível.
    """
    head = content[:4096]
    return all(marker in head for marker in CHALLENGE_MARKERS)


class _Retryable(Exception):
    """Interno: sinaliza ao loop de retry que a tentativa pode ser repetida."""


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


# -- fachada de módulo --------------------------------------------------------

_default: Fetcher | None = None


def get_fetcher(settings: Settings) -> Fetcher:
    """Devolve um Fetcher único por processo (reaproveita sessão e rate limit).

    Se as settings mudarem (ex.: outra data), cria um novo.
    """
    global _default
    if _default is None or _default.settings is not settings:
        _default = Fetcher(settings)
    return _default


def fetch(settings: Settings, kind: str, key: str | None = None, *, force: bool = False) -> str:
    return get_fetcher(settings).fetch(kind, key, force=force)
