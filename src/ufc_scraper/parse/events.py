"""Parser da lista de eventos e do card de cada evento (spec §4: `events` e parte de `fights`).

Funções puras: recebem HTML e devolvem `list[dict]`. Nenhum acesso a disco/rede.

Card do evento (`tr.b-fight-details__table-row` com `data-link` da luta), colunas:
    0 W/L (1 flag `win` = vencedor listado PRIMEIRO; 2 flags `draw`/`nc`)
    1 lutadores (2 links, ordem da página)   2 KD   3 STR   4 TD   5 SUB
    6 categoria (+ ícones: belt = título; fight/perf/sub/ko = bônus)
    7 método (2 linhas: sigla + detalhe)     8 round   9 tempo

Nota para a análise: como o vencedor vem primeiro, `fighter_a` ≈ vencedor em
quase todas as lutas com resultado. A spec manda manter a ordem da página e
deixar qualquer sorteio para a etapa de análise.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

from ..config import Settings
from ..links import extract_id
from ..normalize import (
    clean_text,
    normalize_method,
    normalize_weight_class,
    parse_date,
    parse_int,
    parse_mmss,
    went_to_decision,
)
from ..paths import url_for

log = logging.getLogger(__name__)

EVENTS_COLUMNS = ["event_id", "name", "date", "location", "scraped_at", "source_url"]

# Ícones da coluna de categoria. `belt` vira is_title_fight, não bônus.
BONUS_ICONS = {
    "fight.png": "fight_of_the_night",
    "perf.png": "performance_of_the_night",
    "sub.png": "submission_of_the_night",
    "ko.png": "ko_of_the_night",
}
TITLE_ICON = "belt.png"
NEXT_EVENT_ICON = "next.png"


def _li_fields(soup: Tag) -> dict[str, str | None]:
    """`<li class=b-list__box-list-item><i>Date:</i> valor</li>` -> {"Date": valor}."""
    out: dict[str, str | None] = {}
    for li in soup.select("li.b-list__box-list-item"):
        label = li.select_one("i")
        if label is None:
            continue
        key = clean_text(label.get_text(" ", strip=True)) or ""
        label_text = label.get_text(" ", strip=True)
        value = li.get_text(" ", strip=True).replace(label_text, "", 1)
        out[key.rstrip(":")] = clean_text(value)
    return out


# -- lista de eventos ---------------------------------------------------------


def parse_events_list(html: str, settings: Settings) -> list[dict]:
    """Uma linha por evento realizado (pula o próximo evento futuro, ícone next.png)."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()
    for tr in soup.select("tr"):
        a = tr.select_one("a[href*='/event-details/']")
        if a is None:
            continue
        if tr.find("img", src=lambda s: bool(s) and NEXT_EVENT_ICON in s):
            continue
        event_id = extract_id(a["href"])
        if event_id in seen:
            continue
        seen.add(event_id)
        date_el = tr.select_one("span.b-statistics__date")
        tds = tr.select("td")
        location = clean_text(tds[1].get_text(" ", strip=True)) if len(tds) > 1 else None
        rows.append(
            {
                "event_id": event_id,
                "name": clean_text(a.get_text(" ", strip=True)),
                "date": parse_date(date_el.get_text(" ", strip=True)) if date_el else None,
                "location": location,
                "scraped_at": settings.date,
                "source_url": url_for("event", event_id, settings.base_url),
            }
        )
    return rows


# -- página do evento ---------------------------------------------------------


def parse_event_header(html: str, event_id: str, settings: Settings) -> dict:
    """Mesmos campos de `events`, lidos da página do evento (usado como checagem/fallback)."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one("span.b-content__title-highlight")
    fields = _li_fields(soup)
    return {
        "event_id": event_id,
        "name": clean_text(title.get_text(" ", strip=True)) if title else None,
        "date": parse_date(fields.get("Date")),
        "location": fields.get("Location"),
        "scraped_at": settings.date,
        "source_url": url_for("event", event_id, settings.base_url),
    }


def _ps(td: Tag) -> list[str | None]:
    return [clean_text(p.get_text(" ", strip=True)) for p in td.select("p")]


def _icons(td: Tag) -> list[str]:
    return [img["src"].rsplit("/", 1)[-1].lower() for img in td.select("img") if img.get("src")]


def parse_event_card(html: str, event_id: str, settings: Settings) -> list[dict]:
    """Linhas PARCIAIS de `fights` (campos disponíveis no card). `card_position` = 1 é o main event."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for tr in soup.select("tr.b-fight-details__table-row"):
        tds = tr.select("td")
        if len(tds) < 10:
            continue  # cabeçalho ou linha vazia
        link = tr.get("data-link") or (tds[0].select_one("a") or {}).get("href")
        if not link:
            log.warning("evento %s: linha do card sem link de luta", event_id)
            continue
        fight_id = extract_id(link)

        fighters = [extract_id(a["href"]) for a in tds[1].select("a[href*='/fighter-details/']")]
        if len(fighters) != 2:
            log.warning("evento %s luta %s: %d lutadores na linha (esperado 2)", event_id, fight_id, len(fighters))
            fighters = (fighters + [None, None])[:2]

        flags = [clean_text(i.get_text(" ", strip=True)) for i in tds[0].select("i.b-flag__text")]
        flags = [f.lower() for f in flags if f]
        if "win" in flags:
            result_type, winner = "win", fighters[flags.index("win")]
        elif "draw" in flags:
            result_type, winner = "draw", None
        elif "nc" in flags:
            result_type, winner = "no_contest", None
        else:
            log.warning("evento %s luta %s: flag de resultado desconhecido %r", event_id, fight_id, flags)
            result_type, winner = None, None

        weight_raw = clean_text(tds[6].get_text(" ", strip=True))
        weight_class, is_title, is_women = normalize_weight_class(weight_raw)
        icons = _icons(tds[6])
        if TITLE_ICON in icons:
            is_title = True
        bonuses = []
        for icon in icons:
            if icon == TITLE_ICON:
                continue
            name = BONUS_ICONS.get(icon)
            if name is None:
                log.warning("evento %s luta %s: ícone desconhecido %r", event_id, fight_id, icon)
                name = icon.rsplit(".", 1)[0]
            bonuses.append(name)

        method_ps = _ps(tds[7])
        method_raw = method_ps[0] if method_ps else None
        method, method_detail = normalize_method(method_raw, method_ps[1] if len(method_ps) > 1 else None)

        rows.append(
            {
                "fight_id": fight_id,
                "event_id": event_id,
                "card_position": len(rows) + 1,
                "fighter_a_id": fighters[0],
                "fighter_b_id": fighters[1],
                "winner_id": winner,
                "result_type": result_type,
                "weight_class": weight_class,
                "weight_class_raw": weight_raw,
                "is_title_fight": is_title,
                "is_women": is_women,
                "bonuses": bonuses,
                "method": method,
                "method_raw": method_raw,
                "method_detail": method_detail,
                "went_to_decision": went_to_decision(method),
                "end_round": parse_int(_ps(tds[8])[0] if _ps(tds[8]) else None),
                "end_time_seconds": parse_mmss(_ps(tds[9])[0] if _ps(tds[9]) else None),
                "scraped_at": settings.date,
                "source_url": url_for("fight", fight_id, settings.base_url),
            }
        )
    return rows
