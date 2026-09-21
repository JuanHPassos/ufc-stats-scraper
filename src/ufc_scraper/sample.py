"""Sorteio de lutas para conferência manual (spec §7: 10 lutas de épocas diferentes).

Estratifica por era (antes de 2005, 2005–2015, 2016+), com no mínimo `min_per_era`
de cada uma; o restante é distribuído em rodízio entre as eras. Determinístico
por `seed`. Se uma era tem menos lutas que a cota (coleta parcial), pega o que há
e avisa.
"""

from __future__ import annotations

import logging
import random

import pandas as pd

from .config import Settings
from .paths import processed_dir

log = logging.getLogger(__name__)

ERAS = (("pre-2005", None, 2004), ("2005-2015", 2005, 2015), ("2016+", 2016, None))


def era_of(year: int | None) -> str | None:
    if year is None or pd.isna(year):
        return None
    for name, lo, hi in ERAS:
        if (lo is None or year >= lo) and (hi is None or year <= hi):
            return name
    return None


def sample_fights(fights: pd.DataFrame, events: pd.DataFrame, n: int = 10, seed: int = 42, min_per_era: int = 2) -> pd.DataFrame:
    """Devolve `n` lutas (linhas de `fights` + `date`, `year`, `era`), estratificadas por era."""
    if fights.empty or events.empty:
        return pd.DataFrame(columns=[*fights.columns, "date", "event_name", "year", "era"])
    f = fights.merge(events[["event_id", "date", "name"]].rename(columns={"name": "event_name"}), on="event_id", how="left")
    f["year"] = pd.to_datetime(f.date, errors="coerce").dt.year
    f["era"] = f.year.map(era_of)
    f = f[f.era.notna()].sort_values("fight_id").reset_index(drop=True)
    if f.empty:
        return f

    rng = random.Random(seed)
    by_era = {name: list(f.index[f.era == name]) for name, _, _ in ERAS}
    for idxs in by_era.values():
        rng.shuffle(idxs)

    chosen: list[int] = []
    for name, idxs in by_era.items():
        take = idxs[:min_per_era]
        if len(take) < min_per_era:
            log.warning("era %s tem só %d luta(s) (cota mínima %d) — coleta parcial?", name, len(take), min_per_era)
        chosen += take
        del idxs[: len(take)]
    # restante em rodízio, para não concentrar numa era
    while len(chosen) < n and any(by_era.values()):
        for idxs in by_era.values():
            if idxs and len(chosen) < n:
                chosen.append(idxs.pop())
    chosen = chosen[:n]
    out = f.loc[chosen].sort_values(["year", "fight_id"]).reset_index(drop=True)
    if len(out) < n:
        log.warning("só %d luta(s) disponíveis de %d pedidas", len(out), n)
    return out


def render_fight(row: pd.Series, fight_stats: pd.DataFrame, round_stats: pd.DataFrame) -> str:
    """Bloco legível com todas as colunas da luta e suas estatísticas."""
    fid = row.fight_id
    lines = [f"## {row.era} · {row.year} · {row.event_name}", f"URL: {row.source_url}", ""]
    skip = {"era", "year", "event_name", "date"}
    for col, val in row.items():
        if col not in skip:
            lines.append(f"  {col:22} {'' if pd.isna(val) else val}")
    fs = fight_stats[fight_stats.fight_id == fid].drop(columns=["fight_id", "scraped_at", "source_url"], errors="ignore")
    rs = round_stats[round_stats.fight_id == fid].drop(columns=["fight_id", "scraped_at", "source_url"], errors="ignore")
    lines.append("")
    lines.append("fight_stats:")
    lines.append(fs.to_string(index=False) if len(fs) else "  (sem estatísticas — esperado em lutas antigas)")
    lines.append("")
    lines.append("round_stats:")
    lines.append(rs.sort_values(["round", "fighter_id"]).to_string(index=False) if len(rs) else "  (sem rounds)")
    return "\n".join(lines)


def manual_check_template(sample: pd.DataFrame) -> str:
    """Tabela vazia para `.specify/manual_check.md`: uma linha por luta sorteada."""
    lines = [
        "# Conferência manual — 10 lutas sorteadas",
        "",
        "Sorteio: `scripts/sample_fights.py --n 10 --seed 42`. Conferir campo a campo no site e",
        "preencher `campos divergentes` (ou `nenhum`) e `ação` (correção + teste, ou `—`).",
        "",
        "| # | era | ano | fight_id | URL | campos divergentes | ação |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(sample.itertuples(), 1):
        lines.append(f"| {i} | {r.era} | {r.year} | `{r.fight_id}` | {r.source_url} |  |  |")
    return "\n".join(lines) + "\n"


def load_processed(settings: Settings) -> dict[str, pd.DataFrame]:
    out = processed_dir(settings)
    ids = {c: "string" for c in ("event_id", "fight_id", "fighter_id", "fighter_a_id", "fighter_b_id", "winner_id")}
    return {name: pd.read_csv(out / f"{name}.csv", dtype=ids) for name in ("events", "fights", "fight_stats", "round_stats")}
