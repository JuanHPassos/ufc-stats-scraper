"""Parser do resumo da página da luta (spec §4: campos de `fights` que só existem lá).

Função pura: HTML -> dict. Estrutura relevante da página:

    div.b-fight-details__person (x2, ordem da página)
        i.b-fight-details__person-status  -> W | L | D | NC
        a.b-fight-details__person-link    -> href com o fighter_id
    i.b-fight-details__fight-title        -> categoria (+ ícones belt/fight/perf...)
    div.b-fight-details__content
        p[0]: itens "Method:", "Round:", "Time:", "Time format:", "Referee:"
        p[1]: "Details:" + TEXTO LIVRE (técnica ou motivo) + um <i> por juiz
              com <span>nome</span> 29 - 28.

Os placares dos juízes são lidos item a item (nunca do texto junto), porque em
lutas overturned o texto livre ("Failed Drug Test by X") antecede os placares.

ORDEM DOS LUTADORES: esta página é a fonte de `fighter_a_id`/`fighter_b_id`, porque
no card do evento o vencedor é SEMPRE listado primeiro (ordem sem informação).
Atenção: até 2009 a página da luta também listava o vencedor primeiro (medido na
coleta completa: 1 250/1 250 lutas de 1994–2009); só de 2010 em diante a ordem
reflete os cantos (o 1º vence 54–62%, a vantagem do canto vermelho). O scraper
registra a ordem como o site dá; cabe à análise filtrar por ano ou simetrizar —
ver `coverage_report.md` (`pct_winner_is_a`).

A categoria bruta também vem daqui, porque só esta página distingue
"UFC … Title Bout" de "Road to UFC … Tournament Title Bout".
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup, NavigableString, Tag

from ..config import Settings
from ..links import extract_id
from ..normalize import (
    clean_text,
    normalize_method,
    normalize_weight_class,
    parse_int,
    parse_judges,
    parse_mmss,
    parse_time_format,
    total_fight_seconds,
)

log = logging.getLogger(__name__)

STATUS_TO_RESULT = {"W": "win", "L": "win", "D": "draw", "NC": "no_contest"}


def _text_items(p: Tag) -> dict[str, str | None]:
    """Itens "Label: valor" do primeiro parágrafo."""
    out: dict[str, str | None] = {}
    for it in p.select("i.b-fight-details__text-item_first, i.b-fight-details__text-item"):
        txt = clean_text(it.get_text(" ", strip=True)) or ""
        if ":" in txt:
            k, v = txt.split(":", 1)
            out[k.strip()] = clean_text(v)
    return out


def _details(p: Tag | None) -> tuple[str | None, str | None, list[dict] | None]:
    """(details_raw, texto livre, placares) do parágrafo "Details:"."""
    if p is None:
        return (None, None, None)
    free_parts: list[str] = []
    judge_lines: list[str] = []
    for child in p.children:
        if isinstance(child, NavigableString):
            free_parts.append(str(child))
        elif isinstance(child, Tag):
            cls = child.get("class", [])
            if "b-fight-details__text-item" in cls:
                judge_lines.append(child.get_text(" ", strip=True))
            # `b-fight-details__text-item_first` é o rótulo "Details:" — ignorado
    free = clean_text(" ".join(free_parts))
    judges = parse_judges("\n".join(judge_lines)) if judge_lines else None
    raw_parts = [x for x in [free, *[clean_text(j) for j in judge_lines]] if x]
    details_raw = " ".join(raw_parts) or None
    return (details_raw, free, judges)


def parse_fight_summary(html: str, fight_id: str, settings: Settings) -> dict:
    """Campos exclusivos da página da luta + `check` com o que o card também tem.

    O builder compara `check` com o card e loga divergências (o card manda).
    """
    soup = BeautifulSoup(html, "lxml")

    persons: list[tuple[str | None, str | None]] = []
    for person in soup.select("div.b-fight-details__person"):
        status_el = person.select_one("i.b-fight-details__person-status")
        link = person.select_one("a.b-fight-details__person-link")
        status = clean_text(status_el.get_text(" ", strip=True)) if status_el else None
        fid = extract_id(link["href"]) if link and link.get("href") else None
        persons.append((fid, status.upper() if status else None))
    if len(persons) != 2:
        log.warning("luta %s: %d lutadores na página (esperado 2)", fight_id, len(persons))
        persons = (persons + [(None, None), (None, None)])[:2]

    statuses = [s for _, s in persons]
    if "W" in statuses:
        winner = persons[statuses.index("W")][0]
        result_type = "win"
    elif "D" in statuses:
        winner, result_type = None, "draw"
    elif "NC" in statuses:
        winner, result_type = None, "no_contest"
    else:
        winner, result_type = None, None

    title_el = soup.select_one("i.b-fight-details__fight-title")
    weight_raw = clean_text(title_el.get_text(" ", strip=True)) if title_el else None
    weight_class, is_title, is_women = normalize_weight_class(weight_raw)

    paragraphs = soup.select("div.b-fight-details__content p.b-fight-details__text")
    items = _text_items(paragraphs[0]) if paragraphs else {}
    details_raw, free_text, judges = _details(paragraphs[1] if len(paragraphs) > 1 else None)

    method, method_detail = normalize_method(items.get("Method"))
    end_round = parse_int(items.get("Round"))
    end_time = parse_mmss(items.get("Time"))
    time_format_raw = items.get("Time format")

    return {
        # autoritativos (só esta página tem, ou ela é a fonte melhor)
        "fighter_a_id": persons[0][0],
        "fighter_b_id": persons[1][0],
        "weight_class": weight_class,
        "weight_class_raw": weight_raw,
        "is_women": is_women,
        "time_format_raw": time_format_raw,
        "scheduled_rounds": parse_time_format(time_format_raw),
        "total_fight_seconds": total_fight_seconds(end_round, end_time, time_format_raw),
        "referee": items.get("Referee"),
        "details_raw": details_raw,
        "judges_scores": judges,
        "method_detail": method_detail,  # só quando o método vem como "TKO - X"; complementa o card
        # o card também informa; o builder compara e loga divergências
        "check": {
            "winner_id": winner,
            "result_type": result_type,
            "method": method,
            "end_round": end_round,
            "end_time_seconds": end_time,
            "is_title_fight": is_title,
            "details_free_text": free_text,
        },
    }
