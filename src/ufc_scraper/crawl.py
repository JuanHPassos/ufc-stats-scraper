"""Orquestração da coleta (spec §2 e §6).

Percorre lista de eventos -> eventos -> lutas -> lutadores, e também a lista
A–Z de lutadores, salvando tudo no cache via `http.fetch`. É retomável: rodar
de novo com a mesma `--date` só baixa o que falta.
"""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field

from .config import Settings
from .http import FetchError, Fetcher, NotFound, get_fetcher
from .links import event_ids, fight_ids, fighter_ids
from .paths import processed_dir, url_for

log = logging.getLogger(__name__)

FAILURES_FILE = "crawl_failures.txt"


@dataclass
class CrawlReport:
    events: int = 0
    fights: int = 0
    fighters: int = 0
    fighters_lists: int = 0
    not_found: int = 0
    failed: int = 0
    fetcher_stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        fs = self.fetcher_stats
        return (
            f"eventos={self.events} lutas={self.fights} lutadores={self.fighters} "
            f"listas_az={self.fighters_lists} | requisições={fs.get('requests', 0)} "
            f"cache_hits={fs.get('cache_hits', 0)} retries={fs.get('retries', 0)} "
            f"desafios={fs.get('challenges', 0)} | 404={self.not_found} falhas={self.failed}"
        )


class Crawler:
    def __init__(self, settings: Settings, fetcher: Fetcher | None = None):
        self.settings = settings
        self.fetcher = fetcher or get_fetcher(settings)
        self.report = CrawlReport()
        self._failures_path = processed_dir(settings) / FAILURES_FILE

    # -- fluxo ----------------------------------------------------------------

    def run(self, limit: int | None = None) -> CrawlReport:
        """Coleta completa. Com `limit`, só os N eventos mais recentes e sem a lista A–Z."""
        try:
            self._run(limit)
        finally:
            self.report.fetcher_stats = dict(self.fetcher.stats)
            log.info("coleta encerrada: %s", self.report.summary())
        return self.report

    def _run(self, limit: int | None) -> None:
        html = self.fetcher.fetch("events_list")
        ids = event_ids(html)
        if limit is not None:
            ids = ids[:limit]
        log.info("%d eventos na lista%s", len(ids), f" (limit={limit})" if limit else "")

        fighters: list[str] = []
        seen: set[str] = set()

        def add_fighters(new: list[str]) -> None:
            for fid in new:
                if fid not in seen:
                    seen.add(fid)
                    fighters.append(fid)

        for i, eid in enumerate(ids, 1):
            event_html = self._get("event", eid)
            if event_html is None:
                continue
            self.report.events += 1
            add_fighters(fighter_ids(event_html))
            fids = fight_ids(event_html)
            log.info("evento %d/%d %s: %d lutas", i, len(ids), eid, len(fids))
            for fid in fids:
                fight_html = self._get("fight", fid)
                if fight_html is None:
                    continue
                self.report.fights += 1
                add_fighters(fighter_ids(fight_html))

        if limit is None:
            for letter in string.ascii_lowercase:
                list_html = self._get("fighters_list", letter)
                if list_html is None:
                    continue
                self.report.fighters_lists += 1
                add_fighters(fighter_ids(list_html))
        else:
            log.info("lista A–Z pulada (limit)")

        log.info("%d lutadores únicos para baixar", len(fighters))
        for i, fid in enumerate(fighters, 1):
            if self._get("fighter", fid) is not None:
                self.report.fighters += 1
            if i % 100 == 0 or i == len(fighters):
                log.info("lutadores %d/%d", i, len(fighters))

    # -- helpers --------------------------------------------------------------

    def _get(self, kind: str, key: str) -> str | None:
        """fetch com tratamento de erro por página: 404 e falhas não param a coleta.

        `ChallengeRequired` NÃO é tratado aqui: se o desafio anti-bot passar a
        falhar, todas as páginas falhariam, então deixamos propagar e abortar.
        """
        try:
            return self.fetcher.fetch(kind, key)
        except NotFound:
            self.report.not_found += 1
            log.warning("404 %s %s", kind, key)
            self._record_failure(kind, key, "404")
        except FetchError as exc:
            self.report.failed += 1
            log.error("falha %s %s: %s", kind, key, exc)
            self._record_failure(kind, key, str(exc))
        return None

    def _record_failure(self, kind: str, key: str, error: str) -> None:
        self._failures_path.parent.mkdir(parents=True, exist_ok=True)
        with self._failures_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{kind}\t{key}\t{url_for(kind, key, self.settings.base_url)}\t{error}\n")


def run_crawl(settings: Settings, limit: int | None = None, fetcher: Fetcher | None = None) -> CrawlReport:
    return Crawler(settings, fetcher).run(limit)
