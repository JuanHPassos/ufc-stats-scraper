"""Builders: percorrem `data/raw/<date>/`, chamam os parsers e escrevem CSV em
`data/processed/<date>/`. Nunca acessam a rede.

Cada `build_<tabela>(settings) -> DataFrame` é registrado em `BUILDERS`; a CLI
`parse --table X` chama um, e `parse` sem `--table` chama todos em ordem.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pandas as pd

from ..config import Settings
from ..paths import cache_path, processed_dir, raw_dir
from .events import EVENTS_COLUMNS, parse_event_card, parse_events_list
from .fights import parse_fight_summary

log = logging.getLogger(__name__)

FIGHTS_COLUMNS = [
    "fight_id", "event_id", "card_position",
    "fighter_a_id", "fighter_b_id", "fighter_order_source", "winner_id", "result_type",
    "weight_class", "weight_class_raw", "is_title_fight", "is_women", "bonuses",
    "method", "method_raw", "method_detail", "went_to_decision",
    "end_round", "end_time_seconds", "total_fight_seconds", "scheduled_rounds", "time_format_raw",
    "referee", "judges_scores", "details_raw",
    "scraped_at", "source_url",
]

# Campos do card que a página da luta também informa; divergência vira WARNING (card prevalece).
_CHECK_FIELDS = ("winner_id", "result_type", "method", "end_round", "end_time_seconds")


def read_raw(settings: Settings, kind: str, key: str | None = None) -> str | None:
    path = cache_path(settings, kind, key)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def raw_ids(settings: Settings, subdir: str) -> list[str]:
    d = raw_dir(settings) / subdir
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.html"))


def _to_json(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def write_csv(df: pd.DataFrame, settings: Settings, name: str) -> Path:
    out = processed_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.csv"
    df.to_csv(path, index=False)
    log.info("%s: %d linhas -> %s", name, len(df), path)
    return path


# -- events -------------------------------------------------------------------


def build_events(settings: Settings) -> pd.DataFrame:
    html = read_raw(settings, "events_list")
    if html is None:
        raise FileNotFoundError(f"lista de eventos não encontrada em {raw_dir(settings)}")
    rows = parse_events_list(html, settings)
    df = pd.DataFrame(rows, columns=EVENTS_COLUMNS)
    write_csv(df, settings, "events")
    return df


# -- fights -------------------------------------------------------------------


def attribute_scores(judges: list[dict] | None, winner_id, fighter_a_id, fighter_b_id) -> list[dict] | None:
    """Mapeia os placares literais (`score_1`, `score_2`) para `score_a`/`score_b`.

    O site não lista os placares na ordem dos lutadores da página; o lado favorecido
    pela MAIORIA dos juízes é, por definição, o vencedor. Sem vencedor (empate, NC)
    ou sem maioria, `score_a`/`score_b` ficam nulos e só a ordem literal é mantida.
    """
    if not judges:
        return None
    favor_1 = sum(j["score_1"] > j["score_2"] for j in judges)
    favor_2 = sum(j["score_2"] > j["score_1"] for j in judges)
    winner_side = None
    if winner_id is not None and winner_id in (fighter_a_id, fighter_b_id):
        if favor_1 > favor_2:
            winner_side = 1
        elif favor_2 > favor_1:
            winner_side = 2
    out = []
    for j in judges:
        entry = {"judge": j["judge"], "score_1": j["score_1"], "score_2": j["score_2"], "score_a": None, "score_b": None}
        if winner_side is not None:
            win_score, lose_score = (j["score_1"], j["score_2"]) if winner_side == 1 else (j["score_2"], j["score_1"])
            if winner_id == fighter_a_id:
                entry["score_a"], entry["score_b"] = win_score, lose_score
            else:
                entry["score_a"], entry["score_b"] = lose_score, win_score
        out.append(entry)
    return out


def _merge_fight(row: dict, summary: dict | None) -> int:
    """Junta o card (`row`, in place) com o resumo da página da luta. Devolve nº de divergências.

    - `fighter_a/b_id` e `weight_class_raw`: página da luta (ordem dos cantos); o card
      (vencedor primeiro) só entra como fallback, marcado em `fighter_order_source`.
    - `is_title_fight`: cinturão no card OU "title" no título da página.
    - Demais campos compartilhados: card prevalece; divergência vira WARNING.
    """
    fid = row["fight_id"]
    if summary is None:
        row["fighter_order_source"] = "card"
        return 0
    check = summary.pop("check")
    mismatches = 0

    page_pair = {summary["fighter_a_id"], summary["fighter_b_id"]}
    card_pair = {row["fighter_a_id"], row["fighter_b_id"]}
    if None not in page_pair and page_pair == card_pair:
        row["fighter_a_id"], row["fighter_b_id"] = summary["fighter_a_id"], summary["fighter_b_id"]
        row["fighter_order_source"] = "fight_page"
    else:
        mismatches += 1
        log.warning("luta %s: lutadores da página %s ≠ card %s; mantendo card", fid, page_pair, card_pair)
        row["fighter_order_source"] = "card"

    if summary["weight_class_raw"]:
        row["weight_class_raw"] = summary["weight_class_raw"]
        if summary["weight_class"] != row["weight_class"]:
            mismatches += 1
            log.warning("luta %s: categoria página=%r ≠ card=%r; usando página", fid, summary["weight_class"], row["weight_class"])
        row["weight_class"] = summary["weight_class"]
        row["is_women"] = summary["is_women"]
    row["is_title_fight"] = bool(row.get("is_title_fight")) or bool(check.get("is_title_fight"))

    for field in _CHECK_FIELDS:
        if check.get(field) != row.get(field):
            mismatches += 1
            log.warning("luta %s: %s difere (card=%r, página=%r); card prevalece", fid, field, row.get(field), check.get(field))

    for key in ("time_format_raw", "scheduled_rounds", "total_fight_seconds", "referee", "details_raw"):
        row[key] = summary[key]
    if row.get("method_detail") is None and summary.get("method_detail"):
        row["method_detail"] = summary["method_detail"]
    judges = summary["judges_scores"]
    row["judges_scores"] = attribute_scores(judges, row["winner_id"], row["fighter_a_id"], row["fighter_b_id"])
    if judges and row["result_type"] == "win":
        favor_2 = sum(j["score_2"] > j["score_1"] for j in judges)
        if favor_2 <= len(judges) / 2:
            mismatches += 1
            log.warning("luta %s: placares não favorecem o 2º número (convenção observada); conferir", fid)
    return mismatches


def build_fights(settings: Settings) -> pd.DataFrame:
    rows: list[dict] = []
    missing_pages = 0
    mismatches = 0
    for event_id in raw_ids(settings, "events"):
        card = parse_event_card(read_raw(settings, "event", event_id), event_id, settings)
        for row in card:
            fight_html = read_raw(settings, "fight", row["fight_id"])
            if fight_html is None:
                missing_pages += 1
                log.warning("luta %s (evento %s): página da luta ausente; campos nulos", row["fight_id"], event_id)
                summary = None
            else:
                summary = parse_fight_summary(fight_html, row["fight_id"], settings)
            mismatches += _merge_fight(row, summary)
            row["bonuses"] = _to_json(row.get("bonuses"))
            row["judges_scores"] = _to_json(row.get("judges_scores"))
            rows.append(row)

    df = pd.DataFrame(rows, columns=FIGHTS_COLUMNS)
    for col in ("end_round", "end_time_seconds", "total_fight_seconds", "scheduled_rounds", "card_position"):
        df[col] = df[col].astype("Int64")
    for col in ("is_title_fight", "is_women", "went_to_decision"):
        df[col] = df[col].astype("boolean")
    log.info("fights: %d lutas, %d sem página, %d divergências card/página", len(df), missing_pages, mismatches)
    write_csv(df, settings, "fights")
    return df


BUILDERS: dict[str, Callable[[Settings], pd.DataFrame]] = {
    "events": build_events,
    "fights": build_fights,
}
