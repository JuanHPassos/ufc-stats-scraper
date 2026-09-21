"""Parser do perfil do lutador e da lista A–Z (spec §4: `fighters`).

Funções puras: HTML -> dict / list[dict]. O perfil é a fonte da tabela; a lista
A–Z serve só para conferir cobertura (todo ID listado deve ter perfil salvo).

Cartel e estatísticas de carreira são um retrato da data da coleta (spec §8):
ficam na tabela como referência, mas não devem virar feature pré-luta na análise
(vazamento de dados). Os percentuais de carreira são mantidos como decimal 0–1
porque não há landed/attempted no perfil para recalcular. A lista de lutas do
perfil NÃO é extraída (já está em `fights`).
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup, Tag

from ..config import Settings
from ..links import extract_id
from ..normalize import (
    clean_text,
    parse_date,
    parse_float,
    parse_height,
    parse_percent,
    parse_reach,
    parse_record,
    parse_weight,
)
from ..paths import url_for

log = logging.getLogger(__name__)

FIGHTERS_COLUMNS = [
    "fighter_id", "name", "nickname",
    "height_cm", "weight_kg", "reach_cm", "stance", "dob",
    "wins", "losses", "draws", "nc",
    "slpm", "str_acc", "sapm", "str_def", "td_avg", "td_acc", "td_def", "sub_avg",
    "scraped_at", "source_url",
]

# rótulo no perfil -> (coluna, conversor)
_FIELDS = {
    "Height": ("height_cm", parse_height),
    "Weight": ("weight_kg", parse_weight),
    "Reach": ("reach_cm", parse_reach),
    "STANCE": ("stance", clean_text),
    "DOB": ("dob", parse_date),
    "SLpM": ("slpm", parse_float),
    "Str. Acc.": ("str_acc", parse_percent),
    "SApM": ("sapm", parse_float),
    "Str. Def": ("str_def", parse_percent),
    "TD Avg.": ("td_avg", parse_float),
    "TD Acc.": ("td_acc", parse_percent),
    "TD Def.": ("td_def", parse_percent),
    "Sub. Avg.": ("sub_avg", parse_float),
}


def _li_fields(soup: Tag) -> dict[str, str | None]:
    """`<li><i>Height:</i> 5' 5"</li>` -> {"Height": "5' 5\""}; itens sem rótulo são ignorados."""
    out: dict[str, str | None] = {}
    for li in soup.select("li.b-list__box-list-item"):
        label = li.select_one("i")
        if label is None:
            continue
        label_text = label.get_text(" ", strip=True)
        key = (clean_text(label_text) or "").rstrip(":")
        if not key:
            continue
        out[key] = clean_text(li.get_text(" ", strip=True).replace(label_text, "", 1))
    return out


def parse_fighter(html: str, fighter_id: str, settings: Settings) -> dict:
    soup = BeautifulSoup(html, "lxml")
    name_el = soup.select_one("span.b-content__title-highlight")
    record_el = soup.select_one("span.b-content__title-record")
    nick_el = soup.select_one("p.b-content__Nickname")

    row: dict = {col: None for col in FIGHTERS_COLUMNS}
    row.update(
        fighter_id=fighter_id,
        name=clean_text(name_el.get_text(" ", strip=True)) if name_el else None,
        nickname=clean_text(nick_el.get_text(" ", strip=True)) if nick_el else None,
        scraped_at=settings.date,
        source_url=url_for("fighter", fighter_id, settings.base_url),
    )
    if row["name"] is None:
        log.warning("lutador %s: perfil sem nome", fighter_id)

    if record_el is not None:
        try:
            row["wins"], row["losses"], row["draws"], row["nc"] = parse_record(record_el.get_text(" ", strip=True))
        except ValueError as exc:
            log.warning("lutador %s: %s", fighter_id, exc)

    fields = _li_fields(soup)
    for label, (col, conv) in _FIELDS.items():
        raw = fields.get(label)
        try:
            row[col] = conv(raw)
        except ValueError as exc:
            log.warning("lutador %s: %s", fighter_id, exc)
            row[col] = None
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        log.warning("lutador %s: rótulos desconhecidos no perfil: %s", fighter_id, sorted(unknown))
    return row


def parse_fighters_list(html: str, settings: Settings) -> list[dict]:
    """Lista A–Z: uma linha por lutador (`fighter_id`, `name`, `nickname`), deduplicada."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()
    for tr in soup.select("table tbody tr"):
        tds = tr.select("td")
        link = tr.select_one("a[href*='/fighter-details/']")
        if link is None or len(tds) < 3:
            continue
        fid = extract_id(link["href"])
        if fid in seen:
            continue
        seen.add(fid)
        first = clean_text(tds[0].get_text(" ", strip=True)) or ""
        last = clean_text(tds[1].get_text(" ", strip=True)) or ""
        rows.append(
            {
                "fighter_id": fid,
                "name": clean_text(f"{first} {last}"),
                "nickname": clean_text(tds[2].get_text(" ", strip=True)),
            }
        )
    return rows
