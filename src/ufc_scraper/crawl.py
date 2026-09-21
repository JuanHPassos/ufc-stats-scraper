"""Orquestração da coleta (spec §2 e §6).

Percorre lista de eventos -> eventos -> lutas -> lutadores, e também a lista
A–Z de lutadores, salvando tudo no cache via `http.fetch`. É retomável: rodar
de novo com a mesma `--date` só baixa o que falta.
"""

from __future__ import annotations

import filecmp
import json
import logging
import os
import shutil
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .http import FetchError, Fetcher, NotFound, get_fetcher
from .links import event_ids, fight_ids, fighter_ids
from .paths import cache_path, processed_dir, raw_dir, url_for

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
    # só no modo incremental
    new_events: int = 0
    refreshed_fighters: int = 0
    copied: int = 0

    def summary(self) -> str:
        fs = self.fetcher_stats
        inc = f" | novos_eventos={self.new_events} perfis_renovados={self.refreshed_fighters} copiados={self.copied}" if self.copied or self.new_events else ""
        return (
            f"eventos={self.events} lutas={self.fights} lutadores={self.fighters} "
            f"listas_az={self.fighters_lists} | requisições={fs.get('requests', 0)} "
            f"cache_hits={fs.get('cache_hits', 0)} retries={fs.get('retries', 0)} "
            f"desafios={fs.get('challenges', 0)} | 404={self.not_found} falhas={self.failed}{inc}"
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

    # -- incremental ----------------------------------------------------------

    def run_incremental(self, base_date: str) -> CrawlReport:
        """Nova pasta `raw/<date>/` a partir de `raw/<base_date>/`, baixando só o que mudou.

        Baixa: lista de eventos, eventos novos (+ lutas), perfis dos lutadores envolvidos
        nos eventos novos (o cartel mudou), as 26 listas A–Z (2ª rota da spec) e perfis
        de lutadores que apareceram nelas. Todo o resto é COPIADO da base (hard link;
        a base nunca é alterada). Ordem: baixa primeiro, copia o que faltar depois — assim
        uma retomada é correta (o que já foi baixado é cache hit; cópias são puladas).
        """
        try:
            self._run_incremental(base_date)
        finally:
            self.report.fetcher_stats = dict(self.fetcher.stats)
            log.info("coleta incremental encerrada: %s", self.report.summary())
        return self.report

    def _run_incremental(self, base_date: str) -> None:
        s = self.settings
        if base_date == s.date:
            raise ValueError("--base-date deve ser diferente de --date")
        base = Settings(**{**asdict(s), "date": base_date})
        base_events = raw_dir(base) / "events"
        if not base_events.is_dir():
            raise FileNotFoundError(f"coleta-base não encontrada: {raw_dir(base)}")
        base_event_ids = {p.stem for p in base_events.glob("*.html")}
        base_fighter_ids = {p.stem for p in (raw_dir(base) / "fighters").glob("*.html")}

        html = self.fetcher.fetch("events_list")
        ids = event_ids(html)
        new_ids = [eid for eid in ids if eid not in base_event_ids]
        self.report.new_events = len(new_ids)
        log.info("incremental sobre %s: %d eventos na lista, %d novos", base_date, len(ids), len(new_ids))

        involved: list[str] = []
        seen: set[str] = set()

        def add(new: list[str]) -> None:
            for fid in new:
                if fid not in seen:
                    seen.add(fid)
                    involved.append(fid)

        for i, eid in enumerate(new_ids, 1):
            event_html = self._get("event", eid)
            if event_html is None:
                continue
            self.report.events += 1
            add(fighter_ids(event_html))
            fids = fight_ids(event_html)
            log.info("evento novo %d/%d %s: %d lutas", i, len(new_ids), eid, len(fids))
            for fid in fids:
                fight_html = self._get("fight", fid)
                if fight_html is None:
                    continue
                self.report.fights += 1
                add(fighter_ids(fight_html))

        for letter in string.ascii_lowercase:
            list_html = self._get("fighters_list", letter)
            if list_html is None:
                continue
            self.report.fighters_lists += 1
            add([fid for fid in fighter_ids(list_html) if fid not in base_fighter_ids])

        log.info("%d perfis a baixar (envolvidos em eventos novos ou inéditos na lista A–Z)", len(involved))
        for fid in involved:
            new_path = cache_path(s, "fighter", fid)
            base_path = cache_path(base, "fighter", fid)
            # Retomada: se o arquivo na pasta nova é só uma cópia da base, força a renovação.
            force = new_path.exists() and base_path.exists() and _same_content(new_path, base_path)
            try:
                self.fetcher.fetch("fighter", fid, force=force)
            except NotFound:
                self.report.not_found += 1
                self._record_failure("fighter", fid, "404")
                continue
            except FetchError as exc:
                self.report.failed += 1
                self._record_failure("fighter", fid, str(exc))
                continue
            self.report.fighters += 1
            if fid in base_fighter_ids:
                self.report.refreshed_fighters += 1

        self.report.copied = _copy_missing(raw_dir(base), raw_dir(s), skip={"events_list.html", "fighters_list"})
        manifest = {
            "date": s.date,
            "base_date": base_date,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "new_event_ids": new_ids,
            "fighters_fetched": involved,
            "refreshed_fighters": self.report.refreshed_fighters,
            "copied_files": self.report.copied,
        }
        (raw_dir(s) / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

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


def _same_content(a: Path, b: Path) -> bool:
    try:
        if os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return filecmp.cmp(a, b, shallow=False)


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _copy_missing(base: Path, new: Path, skip: set[str]) -> int:
    """Traz para `new` todo arquivo de `base` que ainda não existe lá (hard link ou cópia).
    `skip`: nomes de 1º nível a ignorar (o que o incremental baixa fresco)."""
    copied = 0
    for src in base.rglob("*.html"):
        rel = src.relative_to(base)
        if rel.parts[0] in skip:
            continue
        dst = new / rel
        if dst.exists():
            continue
        _link_or_copy(src, dst)
        copied += 1
    log.info("%d arquivos copiados de %s", copied, base)
    return copied


def latest_base(settings: Settings) -> str | None:
    """Pasta de coleta mais recente em data/raw/ diferente da atual (padrão de --base-date)."""
    root = settings.data_dir / "raw"
    if not root.is_dir():
        return None
    dates = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != settings.date and (p / "events").is_dir())
    return dates[-1] if dates else None


def run_crawl(settings: Settings, limit: int | None = None, fetcher: Fetcher | None = None) -> CrawlReport:
    return Crawler(settings, fetcher).run(limit)


def run_incremental(settings: Settings, base_date: str, fetcher: Fetcher | None = None) -> CrawlReport:
    return Crawler(settings, fetcher).run_incremental(base_date)
