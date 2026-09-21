"""Parser das tabelas de estatísticas da página da luta (spec §4: `fight_stats` e `round_stats`).

Funções puras: HTML -> list[dict]. Uma linha por lutador (e por round, na versão
por round). Página sem tabela (lutas antigas) -> `[]`, nunca linhas com zeros.

Layout da página (2026): quatro tabelas, nesta ordem:
    Totals            (1 tbody tr; cada td tem 2 <p>, um por lutador)
    Totals per round  (thead "Round N" + tbody tr, repetido por round)
    Sig. strikes      (Parte 6)
    Sig. strikes per round (Parte 6)

As tabelas são reconhecidas pelo cabeçalho, e as colunas são lidas por POSIÇÃO:
o cabeçalho por round do site tem um bug ("Td %" duas vezes no lugar de "Td"),
então o nome da coluna não é confiável. Percentuais são descartados (spec §5).
A ordem dos lutadores na tabela é a mesma das pessoas no topo da página.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from ..config import Settings
from ..links import extract_id
from ..normalize import clean_text, parse_int, parse_mmss, parse_of
from ..paths import url_for

log = logging.getLogger(__name__)

# (cabeçalho esperado, nomes das colunas de saída; None = descartar). Índice 0 = Fighter.
TOTALS_HEADER = ["Fighter", "KD", "Sig. str.", "Sig. str. %", "Total str.", "Td", "Td %", "Sub. att", "Rev.", "Ctrl"]
TOTALS_SPEC: list[tuple[str | None, str]] = [
    (None, "id"),          # Fighter
    ("kd", "int"),
    ("sig_str", "of"),
    (None, "skip"),        # Sig. str. %
    ("total_str", "of"),
    ("td", "of"),
    (None, "skip"),        # Td %
    ("sub_att", "int"),
    ("rev", "int"),
    ("ctrl_seconds", "mmss"),
]
TOTALS_COLUMNS = [
    "kd", "sig_str_landed", "sig_str_attempted", "total_str_landed", "total_str_attempted",
    "td_landed", "td_attempted", "sub_att", "rev", "ctrl_seconds",
]

# Seção "Significant Strikes": alvo (head/body/leg) e posição (distance/clinch/ground).
# `sig_str` aqui repete a coluna dos totais; sai como `_sig_check` só para conferência.
SIG_HEADER = ["Fighter", "Sig. str", "Sig. str. %", "Head", "Body", "Leg", "Distance", "Clinch", "Ground"]
SIG_SPEC: list[tuple[str | None, str]] = [
    (None, "id"),
    ("_sig_check", "of"),
    (None, "skip"),
    ("head", "of"),
    ("body", "of"),
    ("leg", "of"),
    ("distance", "of"),
    ("clinch", "of"),
    ("ground", "of"),
]
SIG_COLUMNS = [
    "head_landed", "head_attempted", "body_landed", "body_attempted", "leg_landed", "leg_attempted",
    "distance_landed", "distance_attempted", "clinch_landed", "clinch_attempted", "ground_landed", "ground_attempted",
]
SIG_CHECK_COLUMNS = ["_sig_check_landed", "_sig_check_attempted"]

_ROUND_RE = re.compile(r"^Round\s+(\d+)$", re.I)


def _norm(s: str) -> str:
    return " ".join(s.split()).lower().rstrip(".")


def _headers(table: Tag) -> list[str]:
    thead = table.select_one("thead")
    return [" ".join(th.get_text(" ", strip=True).split()) for th in thead.select("th")] if thead else []


def _find_table(soup: Tag, header_prefix: list[str], per_round: bool) -> Tag | None:
    """Tabela cujo cabeçalho começa com `header_prefix` (comparação normalizada, tolera
    o bug "Td %") e que tem (ou não) cabeçalhos "Round N"."""
    want = [_norm(h) for h in header_prefix]
    for table in soup.select("table"):
        heads = [_norm(h) for h in _headers(table)]
        if len(heads) < len(want):
            continue
        # tolera "td %" onde se esperava "td" (bug do site)
        ok = all(h == w or (w == "td" and h == "td %") for h, w in zip(heads, want))
        if not ok:
            continue
        has_rounds = any(_ROUND_RE.match(" ".join(th.get_text(" ", strip=True).split())) for th in table.select("thead th"))
        if has_rounds == per_round:
            return table
    return None


def _cells(tr: Tag) -> list[list[str | None]]:
    """Cada td -> lista de textos dos seus <p> (um por lutador)."""
    return [[clean_text(p.get_text(" ", strip=True)) for p in td.select("p")] for td in tr.select("td")]


def _fighter_ids(tr: Tag) -> list[str | None]:
    tds = tr.select("td")
    if not tds:
        return []
    return [extract_id(a["href"]) if a.get("href") else None for a in tds[0].select("a")]


def _row_to_records(tr: Tag, spec: list[tuple[str | None, str]], fight_id: str, where: str) -> list[dict]:
    """Uma <tr> (2 <p> por célula) -> 2 dicts, um por lutador."""
    cells = _cells(tr)
    ids = _fighter_ids(tr)
    if len(cells) != len(spec):
        log.warning("luta %s (%s): %d colunas na tabela, esperado %d", fight_id, where, len(cells), len(spec))
        return []
    n = len(ids)
    if n != 2:
        log.warning("luta %s (%s): %d lutadores na tabela, esperado 2", fight_id, where, n)
    records: list[dict] = []
    for i, fid in enumerate(ids):
        rec: dict = {"fighter_id": fid}
        for (name, kind), values in zip(spec, cells):
            if kind in ("id", "skip"):
                continue
            v = values[i] if i < len(values) else None
            if kind == "int":
                rec[name] = parse_int(v)
            elif kind == "of":
                rec[f"{name}_landed"], rec[f"{name}_attempted"] = parse_of(v)
            elif kind == "mmss":
                rec[name] = parse_mmss(v)
        records.append(rec)
    return records


def _iter_round_rows(table: Tag):
    """Pares (round, tr) de uma tabela por round.

    Os <thead>"Round N" ficam DENTRO do <tbody>, cada um seguido do seu <tr>;
    por isso percorre os descendentes em ordem de documento.
    """
    current: int | None = None
    for el in table.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name == "thead":
            txt = " ".join(el.get_text(" ", strip=True).split())
            m = _ROUND_RE.match(txt)
            current = int(m.group(1)) if m else None
        elif el.name == "tr" and current is not None and el.select("td"):
            yield current, el


def _parse_table(html: str, fight_id: str, settings: Settings, header, spec, per_round: bool, where: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = _find_table(soup, header, per_round)
    if table is None:
        log.debug("luta %s: sem tabela %s", fight_id, where)
        return []
    base = {"fight_id": fight_id, "scraped_at": settings.date, "source_url": url_for("fight", fight_id, settings.base_url)}
    out: list[dict] = []
    if per_round:
        for rnd, tr in _iter_round_rows(table):
            for rec in _row_to_records(tr, spec, fight_id, where):
                out.append({**base, "round": rnd, **rec})
    else:
        trs = [tr for tr in table.select("tbody tr") if tr.select("td")]
        if len(trs) != 1:
            log.warning("luta %s (%s): %d linhas na tabela de totais, esperado 1", fight_id, where, len(trs))
        for tr in trs[:1]:
            for rec in _row_to_records(tr, spec, fight_id, where):
                out.append({**base, **rec})
    return out


def parse_totals(html: str, fight_id: str, settings: Settings) -> list[dict]:
    """Seção Totals: 2 linhas (uma por lutador), ou [] se a página não tem estatísticas."""
    return _parse_table(html, fight_id, settings, TOTALS_HEADER, TOTALS_SPEC, per_round=False, where="totals")


def parse_round_totals(html: str, fight_id: str, settings: Settings) -> list[dict]:
    """Seção Totals per round: 2 × N linhas com coluna `round`."""
    return _parse_table(html, fight_id, settings, TOTALS_HEADER, TOTALS_SPEC, per_round=True, where="totals/round")


def parse_sig_strikes(html: str, fight_id: str, settings: Settings) -> list[dict]:
    """Seção Significant Strikes (alvo e posição): 2 linhas, ou [] se não existe."""
    return _parse_table(html, fight_id, settings, SIG_HEADER, SIG_SPEC, per_round=False, where="sig")


def parse_round_sig_strikes(html: str, fight_id: str, settings: Settings) -> list[dict]:
    """Seção Significant Strikes per round: 2 × N linhas com coluna `round`."""
    return _parse_table(html, fight_id, settings, SIG_HEADER, SIG_SPEC, per_round=True, where="sig/round")
