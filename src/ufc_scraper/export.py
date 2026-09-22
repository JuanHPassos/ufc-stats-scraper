"""Exportação das 5 tabelas com tipos explícitos (spec §4: CSV para troca,
Parquet ou SQLite para análise). Lê os CSVs de `data/processed/<date>/`.

Tipos: inteiros nullable (`Int64`), booleanos nullable, datas como `date`,
IDs e textos como `string`; `bonuses` e `judges_scores` ficam como string JSON.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from .config import Settings
from .paths import processed_dir
from .validate import PRIMARY_KEYS, TABLES

log = logging.getLogger(__name__)

_INT = "Int64"
_BOOL = "boolean"
_STR = "string"
_FLOAT = "Float64"
_DATE = "date"

SCHEMA: dict[str, dict[str, str]] = {
    "events": {"event_id": _STR, "name": _STR, "date": _DATE, "location": _STR, "scraped_at": _DATE, "source_url": _STR},
    "fights": {
        "fight_id": _STR, "event_id": _STR, "card_position": _INT,
        "fighter_a_id": _STR, "fighter_b_id": _STR, "fighter_order_source": _STR, "winner_id": _STR, "result_type": _STR,
        "weight_class": _STR, "weight_class_card": _STR, "weight_class_raw": _STR, "is_title_fight": _BOOL, "is_women": _BOOL, "bonuses": _STR,
        "method": _STR, "method_raw": _STR, "method_detail": _STR, "went_to_decision": _BOOL,
        "end_round": _INT, "end_time_seconds": _INT, "total_fight_seconds": _INT, "scheduled_rounds": _INT, "time_format_raw": _STR,
        "referee": _STR, "judges_scores": _STR, "details_raw": _STR, "scraped_at": _DATE, "source_url": _STR,
    },
    "fighters": {
        "fighter_id": _STR, "name": _STR, "nickname": _STR,
        "height_cm": _FLOAT, "weight_kg": _FLOAT, "reach_cm": _FLOAT, "stance": _STR, "dob": _DATE,
        "wins": _INT, "losses": _INT, "draws": _INT, "nc": _INT,
        "slpm": _FLOAT, "str_acc": _FLOAT, "sapm": _FLOAT, "str_def": _FLOAT,
        "td_avg": _FLOAT, "td_acc": _FLOAT, "td_def": _FLOAT, "sub_avg": _FLOAT,
        "scraped_at": _DATE, "source_url": _STR,
    },
}
_STATS = {
    "fight_id": _STR, "fighter_id": _STR,
    **{c: _INT for c in (
        "kd", "sig_str_landed", "sig_str_attempted", "total_str_landed", "total_str_attempted",
        "td_landed", "td_attempted", "sub_att", "rev", "ctrl_seconds",
        "head_landed", "head_attempted", "body_landed", "body_attempted", "leg_landed", "leg_attempted",
        "distance_landed", "distance_attempted", "clinch_landed", "clinch_attempted", "ground_landed", "ground_attempted",
    )},
    "scraped_at": _DATE, "source_url": _STR,
}
SCHEMA["fight_stats"] = _STATS
SCHEMA["round_stats"] = {"fight_id": _STR, "fighter_id": _STR, "round": _INT, **{k: v for k, v in _STATS.items() if k not in ("fight_id", "fighter_id")}}

_SQL_TYPES = {_INT: "INTEGER", _BOOL: "INTEGER", _STR: "TEXT", _FLOAT: "REAL", _DATE: "TEXT"}


def load_typed(settings: Settings, name: str) -> pd.DataFrame:
    """CSV -> DataFrame com o SCHEMA aplicado. Colunas fora do schema geram erro (schema desatualizado)."""
    path = processed_dir(settings) / f"{name}.csv"
    df = pd.read_csv(path, dtype="string", keep_default_na=True)
    schema = SCHEMA[name]
    unknown = set(df.columns) - set(schema)
    if unknown:
        raise ValueError(f"{name}: colunas sem tipo no SCHEMA: {sorted(unknown)}")
    for col, kind in schema.items():
        if col not in df.columns:
            df[col] = pd.Series([pd.NA] * len(df), dtype="string")
        s = df[col]
        if kind == _INT:
            df[col] = pd.to_numeric(s, errors="raise").astype(_INT)
        elif kind == _FLOAT:
            df[col] = pd.to_numeric(s, errors="raise").astype(_FLOAT)
        elif kind == _BOOL:
            df[col] = s.map({"True": True, "False": False, "true": True, "false": False}).astype(_BOOL)
        elif kind == _DATE:
            df[col] = pd.to_datetime(s, errors="raise", format="%Y-%m-%d").dt.date
        else:
            df[col] = s.astype(_STR)
    return df[list(schema)]


def export_parquet(settings: Settings) -> list[Path]:
    out = processed_dir(settings)
    paths = []
    for name in TABLES:
        df = load_typed(settings, name)
        path = out / f"{name}.parquet"
        df.to_parquet(path, index=False, engine="pyarrow")
        log.info("parquet: %s (%d linhas)", path, len(df))
        paths.append(path)
    return paths


def export_sqlite(settings: Settings) -> Path:
    out = processed_dir(settings)
    path = out / "ufc_stats.sqlite"
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        for name in TABLES:
            df = load_typed(settings, name)
            cols = ", ".join(f'"{c}" {_SQL_TYPES[k]}' for c, k in SCHEMA[name].items())
            pk = ", ".join(f'"{c}"' for c in PRIMARY_KEYS[name])
            con.execute(f'CREATE TABLE "{name}" ({cols}, PRIMARY KEY ({pk}))')
            sql_df = df.copy()
            for col, kind in SCHEMA[name].items():
                if kind == _DATE:
                    sql_df[col] = sql_df[col].map(lambda d: d.isoformat() if pd.notna(d) else None)
                elif kind == _BOOL:
                    sql_df[col] = sql_df[col].map(lambda b: None if pd.isna(b) else int(b)).astype("Int64")
            sql_df = sql_df.astype(object).where(sql_df.notna(), None)
            sql_df.to_sql(name, con, if_exists="append", index=False)
            log.info("sqlite: tabela %s (%d linhas)", name, len(df))
        con.commit()
    finally:
        con.close()
    return path


def export(settings: Settings, fmt: str) -> list[Path]:
    if fmt == "csv":
        log.info("csv: já gerado por `parse` em %s", processed_dir(settings))
        return [processed_dir(settings) / f"{n}.csv" for n in TABLES]
    if fmt == "parquet":
        return export_parquet(settings)
    if fmt == "sqlite":
        return [export_sqlite(settings)]
    raise ValueError(f"formato desconhecido: {fmt}")
