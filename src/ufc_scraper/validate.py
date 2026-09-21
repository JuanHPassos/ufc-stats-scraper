"""Critérios de aceite da spec §7: integridade e consistência (bloqueiam) e
cobertura (só relatório).

Cada checagem é `check_<nome>(t: Tables) -> list[str]` (violações; vazia = passou).
`run_validation(settings)` carrega os CSVs de `data/processed/<date>/`, roda tudo,
escreve `validation_report.md` e `coverage_report.md`, e devolve False se alguma
checagem bloqueante falhou.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import Settings
from .links import fight_ids
from .normalize import DECISION_METHODS
from .paths import cache_path, processed_dir, raw_dir

log = logging.getLogger(__name__)

MAX_EXAMPLES = 20
TABLES = ("events", "fights", "fight_stats", "round_stats", "fighters")
PRIMARY_KEYS = {
    "events": ["event_id"],
    "fights": ["fight_id"],
    "fight_stats": ["fight_id", "fighter_id"],
    "round_stats": ["fight_id", "fighter_id", "round"],
    "fighters": ["fighter_id"],
}
OF_PAIRS = ("sig_str", "total_str", "td", "head", "body", "leg", "distance", "clinch", "ground")
STAT_SUMS = (("head", "body", "leg"), ("distance", "clinch", "ground"))
ROUND_SUM_COLUMNS = [
    "kd", "sig_str_landed", "sig_str_attempted", "total_str_landed", "total_str_attempted",
    "td_landed", "td_attempted", "sub_att", "rev", "ctrl_seconds",
    "head_landed", "head_attempted", "body_landed", "body_attempted", "leg_landed", "leg_attempted",
    "distance_landed", "distance_attempted", "clinch_landed", "clinch_attempted", "ground_landed", "ground_attempted",
]


@dataclass
class Tables:
    events: pd.DataFrame
    fights: pd.DataFrame
    fight_stats: pd.DataFrame
    round_stats: pd.DataFrame
    fighters: pd.DataFrame
    # do disco (podem ficar vazios em testes com DataFrames sintéticos)
    raw_event_ids: set[str] = field(default_factory=set)
    card_fight_ids: dict[str, list[str]] = field(default_factory=dict)  # event_id -> lutas do card


def load_tables(settings: Settings) -> Tables:
    out = processed_dir(settings)
    frames = {}
    for name in TABLES:
        path = out / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} não existe; rode `parse` antes de `validate`")
        frames[name] = pd.read_csv(path, dtype={c: "string" for c in ("event_id", "fight_id", "fighter_id", "fighter_a_id", "fighter_b_id", "winner_id")})
    t = Tables(**frames)
    events_dir = raw_dir(settings) / "events"
    if events_dir.exists():
        for p in events_dir.glob("*.html"):
            t.raw_event_ids.add(p.stem)
            t.card_fight_ids[p.stem] = fight_ids(p.read_text(encoding="utf-8", errors="replace"))
    return t


def _examples(items) -> str:
    items = list(items)
    shown = ", ".join(str(x) for x in items[:MAX_EXAMPLES])
    more = f" … (+{len(items) - MAX_EXAMPLES})" if len(items) > MAX_EXAMPLES else ""
    return shown + more


def _violations(mask: pd.Series, df: pd.DataFrame, keys: list[str], what: str) -> list[str]:
    bad = df.loc[mask.fillna(False)]
    if bad.empty:
        return []
    ids = bad[keys].astype(str).agg("/".join, axis=1)
    return [f"{what}: {len(bad)} linha(s) — {_examples(ids)}"]


# -- integridade --------------------------------------------------------------


def check_events_have_html(t: Tables) -> list[str]:
    """Todo evento da lista (= tabela events) tem HTML salvo."""
    if not t.raw_event_ids:
        return []
    missing = sorted(set(t.events.event_id) - t.raw_event_ids)
    return [f"eventos sem HTML: {len(missing)} — {_examples(missing)}"] if missing else []


def check_fights_cover_cards(t: Tables) -> list[str]:
    """Toda luta de todo card está em fights, e toda luta aponta para um evento existente."""
    out = []
    in_table = set(t.fights.fight_id)
    missing = [f"{eid}/{fid}" for eid, fids in t.card_fight_ids.items() for fid in fids if fid not in in_table]
    if missing:
        out.append(f"lutas do card ausentes em fights: {len(missing)} — {_examples(missing)}")
    orphan = t.fights.loc[~t.fights.event_id.isin(set(t.events.event_id)), "fight_id"]
    if len(orphan):
        out.append(f"lutas com event_id fora de events: {len(orphan)} — {_examples(orphan)}")
    return out


def check_fighters_exist(t: Tables) -> list[str]:
    """Todo fighter_id citado em fights (e nas tabelas de stats) existe em fighters."""
    known = set(t.fighters.fighter_id)
    cited = set(t.fights.fighter_a_id.dropna()) | set(t.fights.fighter_b_id.dropna())
    cited |= set(t.fight_stats.fighter_id.dropna()) | set(t.round_stats.fighter_id.dropna())
    missing = sorted(cited - known)
    return [f"fighter_id sem perfil em fighters: {len(missing)} — {_examples(missing)}"] if missing else []


def check_unique_pks(t: Tables) -> list[str]:
    out = []
    for name, keys in PRIMARY_KEYS.items():
        df = getattr(t, name)
        if df[keys].isna().any().any():
            out.append(f"{name}: chave primária com nulo")
        dup = df[df.duplicated(keys, keep=False)]
        if len(dup):
            out.append(f"{name}: {len(dup)} linha(s) com PK duplicada — {_examples(dup[keys].astype(str).agg('/'.join, axis=1).unique())}")
    return out


# -- consistência -------------------------------------------------------------


def _stats_tables(t: Tables):
    yield "fight_stats", t.fight_stats, ["fight_id", "fighter_id"]
    yield "round_stats", t.round_stats, ["fight_id", "fighter_id", "round"]


def check_landed_le_attempted(t: Tables) -> list[str]:
    out = []
    for name, df, keys in _stats_tables(t):
        for p in OF_PAIRS:
            out += _violations(df[f"{p}_landed"] > df[f"{p}_attempted"], df, keys, f"{name}.{p}: landed > attempted")
    return out


def check_sig_le_total(t: Tables) -> list[str]:
    out = []
    for name, df, keys in _stats_tables(t):
        for s in ("landed", "attempted"):
            out += _violations(df[f"sig_str_{s}"] > df[f"total_str_{s}"], df, keys, f"{name}: sig_str_{s} > total_str_{s}")
    return out


def check_sig_breakdown_sums(t: Tables) -> list[str]:
    out = []
    for name, df, keys in _stats_tables(t):
        for parts in STAT_SUMS:
            for s in ("landed", "attempted"):
                cols = [f"{p}_{s}" for p in parts]
                total = df[cols].sum(axis=1, min_count=len(cols))
                mask = total.notna() & df[f"sig_str_{s}"].notna() & (total != df[f"sig_str_{s}"])
                out += _violations(mask, df, keys, f"{name}: {'+'.join(parts)}_{s} ≠ sig_str_{s}")
    return out


def check_round_sums(t: Tables) -> list[str]:
    """Soma dos rounds = totais, para cada coluna, quando os rounds existem."""
    if t.round_stats.empty:
        return []
    keys = ["fight_id", "fighter_id"]
    summed = t.round_stats.groupby(keys)[ROUND_SUM_COLUMNS].sum(min_count=1)
    totals = t.fight_stats.set_index(keys)[ROUND_SUM_COLUMNS]
    common = summed.index.intersection(totals.index)
    out = []
    for col in ROUND_SUM_COLUMNS:
        a, b = summed.loc[common, col], totals.loc[common, col]
        mask = a.notna() & b.notna() & (a != b)
        if mask.any():
            bad = ["/".join(map(str, i)) for i in a.index[mask]]
            out.append(f"round_stats vs fight_stats: soma de {col} difere em {len(bad)} — {_examples(bad)}")
    no_totals = summed.index.difference(totals.index)
    if len(no_totals):
        out.append(f"round_stats sem linha em fight_stats: {len(no_totals)} — {_examples('/'.join(map(str, i)) for i in no_totals)}")
    return out


def check_rounds_vs_fight(t: Tables) -> list[str]:
    f = t.fights
    out = _violations(f.end_round > f.scheduled_rounds, f, ["fight_id"], "fights: end_round > scheduled_rounds")
    if not t.round_stats.empty:
        r = t.round_stats.merge(f[["fight_id", "end_round"]], on="fight_id", how="left")
        out += _violations(r["round"] > r.end_round, r, ["fight_id", "fighter_id", "round"], "round_stats: round > end_round")
    return out


def check_ctrl_le_duration(t: Tables) -> list[str]:
    m = t.fight_stats.merge(t.fights[["fight_id", "total_fight_seconds"]], on="fight_id", how="left")
    return _violations(m.ctrl_seconds > m.total_fight_seconds, m, ["fight_id", "fighter_id"], "fight_stats: ctrl_seconds > total_fight_seconds")


def check_winner_and_result(t: Tables) -> list[str]:
    f = t.fights
    out = []
    bad_winner = f.winner_id.notna() & (f.winner_id != f.fighter_a_id) & (f.winner_id != f.fighter_b_id)
    out += _violations(bad_winner, f, ["fight_id"], "fights: winner_id não é A nem B")
    out += _violations((f.result_type == "win") & f.winner_id.isna(), f, ["fight_id"], "fights: result_type=win sem winner_id")
    out += _violations(f.result_type.isin(["draw", "no_contest"]) & f.winner_id.notna(), f, ["fight_id"], "fights: empate/NC com winner_id")
    out += _violations(f.fighter_a_id == f.fighter_b_id, f, ["fight_id"], "fights: fighter_a_id == fighter_b_id")
    return out


def check_decision_flag(t: Tables) -> list[str]:
    f = t.fights
    expected = f.method.isin(DECISION_METHODS)
    mask = f.method.notna() & (f.went_to_decision.astype("boolean") != expected)
    return _violations(mask, f, ["fight_id"], "fights: went_to_decision incoerente com method")


def check_stats_fighters_belong_to_fight(t: Tables) -> list[str]:
    out = []
    pair = t.fights[["fight_id", "fighter_a_id", "fighter_b_id"]]
    for name, df, keys in _stats_tables(t):
        m = df.merge(pair, on="fight_id", how="left")
        mask = m.fighter_a_id.isna() | ((m.fighter_id != m.fighter_a_id) & (m.fighter_id != m.fighter_b_id))
        out += _violations(mask, m, keys, f"{name}: fighter_id não pertence à luta (ou luta inexistente)")
    return out


INTEGRITY: list[Callable[[Tables], list[str]]] = [
    check_events_have_html, check_fights_cover_cards, check_fighters_exist, check_unique_pks,
]
CONSISTENCY: list[Callable[[Tables], list[str]]] = [
    check_landed_le_attempted, check_sig_le_total, check_sig_breakdown_sums, check_round_sums,
    check_rounds_vs_fight, check_ctrl_le_duration, check_winner_and_result, check_decision_flag,
    check_stats_fighters_belong_to_fight,
]


def run_checks(t: Tables) -> dict[str, dict[str, list[str]]]:
    """{'integridade': {check: violações}, 'consistência': {...}}"""
    return {
        "integridade": {c.__name__: c(t) for c in INTEGRITY},
        "consistência": {c.__name__: c(t) for c in CONSISTENCY},
    }


# -- cobertura (não bloqueia) -------------------------------------------------

RELIABLE_THRESHOLD = 0.95


def coverage_by_year(t: Tables) -> pd.DataFrame:
    """Por ano: nº de lutas e % de lutas com fight_stats, round_stats, ctrl, alvo/posição, juízes."""
    f = t.fights.merge(t.events[["event_id", "date"]], on="event_id", how="left")
    f["year"] = pd.to_datetime(f.date, errors="coerce").dt.year
    fs = t.fight_stats
    with_stats = set(fs.fight_id)
    with_rounds = set(t.round_stats.fight_id)
    with_ctrl = set(fs.loc[fs.ctrl_seconds.notna(), "fight_id"])
    with_target = set(fs.loc[fs.head_landed.notna(), "fight_id"])
    decisions = f[f.went_to_decision.astype("boolean").fillna(False)]
    rows = []
    for year, g in f.groupby("year"):
        n = len(g)
        dec = decisions[decisions.year == year]
        rows.append({
            "year": int(year), "fights": n,
            "pct_fight_stats": round(100 * g.fight_id.isin(with_stats).mean(), 1),
            "pct_round_stats": round(100 * g.fight_id.isin(with_rounds).mean(), 1),
            "pct_ctrl": round(100 * g.fight_id.isin(with_ctrl).mean(), 1),
            "pct_target_position": round(100 * g.fight_id.isin(with_target).mean(), 1),
            "pct_judges_on_decisions": round(100 * dec.judges_scores.notna().mean(), 1) if len(dec) else None,
            "pct_referee": round(100 * g.referee.notna().mean(), 1),
        })
    return pd.DataFrame(rows)


def reliable_from(cov: pd.DataFrame, col: str) -> int | None:
    """Primeiro ano a partir do qual TODOS os anos seguintes têm cobertura ≥ 95 %."""
    if cov.empty:
        return None
    ok = cov.sort_values("year")
    bad_years = ok.loc[ok[col].fillna(0) < 100 * RELIABLE_THRESHOLD, "year"]
    if bad_years.empty:
        return int(ok.year.min())
    after = ok[ok.year > bad_years.max()]
    return int(after.year.min()) if len(after) else None


def null_pct_by_year(t: Tables, name: str) -> pd.DataFrame:
    df = getattr(t, name)
    f = t.fights[["fight_id", "event_id"]].merge(t.events[["event_id", "date"]], on="event_id", how="left")
    f["year"] = pd.to_datetime(f.date, errors="coerce").dt.year
    d = df.merge(f[["fight_id", "year"]], on="fight_id", how="left")
    cols = [c for c in df.columns if c not in ("fight_id", "event_id", "fighter_id", "round", "scraped_at", "source_url")]
    return (d.groupby("year")[cols].apply(lambda g: g.isna().mean() * 100).round(1)).reset_index()


def methods_by_year(t: Tables) -> pd.DataFrame:
    f = t.fights.merge(t.events[["event_id", "date"]], on="event_id", how="left")
    f["year"] = pd.to_datetime(f.date, errors="coerce").dt.year
    return pd.crosstab(f.year, f.method.fillna("(nulo)")).reset_index()


def write_coverage_report(t: Tables, path: Path) -> dict:
    cov = coverage_by_year(t)
    answers = {
        "ctrl_reliable_from": reliable_from(cov, "pct_ctrl"),
        "rounds_reliable_from": reliable_from(cov, "pct_round_stats"),
        "target_reliable_from": reliable_from(cov, "pct_target_position"),
    }
    parts = ["# Relatório de cobertura\n", f"Coleta: `{path.parent.name}`. Não bloqueia a validação.\n"]
    parts.append("## A partir de que ano cada campo é confiável (≥ 95 % das lutas, sem regressão depois)\n")
    parts.append(f"- tempo de controle (`ctrl_seconds`): **{answers['ctrl_reliable_from']}**")
    parts.append(f"- estatísticas por round (`round_stats`): **{answers['rounds_reliable_from']}**")
    parts.append(f"- alvo/posição dos golpes significativos: **{answers['target_reliable_from']}**\n")
    parts.append("## Cobertura por ano (% de lutas com o dado)\n")
    parts.append(cov.to_markdown(index=False) if not cov.empty else "_sem dados_")
    parts.append("\n## Lutas por método e ano\n")
    parts.append(methods_by_year(t).to_markdown(index=False))
    for name in ("fights", "fight_stats", "round_stats"):
        parts.append(f"\n## % de nulos por coluna e ano — `{name}`\n")
        parts.append(null_pct_by_year(t, name).to_markdown(index=False))
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return answers


# -- relatório e entrada ------------------------------------------------------


def write_validation_report(results: dict, t: Tables, path: Path) -> bool:
    ok = all(not v for group in results.values() for v in group.values())
    lines = ["# Relatório de validação\n", f"Coleta: `{path.parent.name}` · resultado: **{'PASSOU' if ok else 'FALHOU'}**\n"]
    lines.append("| tabela | linhas |\n| --- | --- |")
    lines += [f"| {n} | {len(getattr(t, n))} |" for n in TABLES]
    for group, checks in results.items():
        lines.append(f"\n## {group}\n")
        lines.append("| checagem | status | detalhes |\n| --- | --- | --- |")
        for name, viol in checks.items():
            status = "✅" if not viol else "❌"
            detail = "<br>".join(viol) if viol else ""
            lines.append(f"| `{name}` | {status} | {detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


def run_validation(settings: Settings) -> bool:
    t = load_tables(settings)
    results = run_checks(t)
    out = processed_dir(settings)
    ok = write_validation_report(results, t, out / "validation_report.md")
    answers = write_coverage_report(t, out / "coverage_report.md")
    for group, checks in results.items():
        for name, viol in checks.items():
            if viol:
                log.error("%s/%s: %s", group, name, " | ".join(viol))
            else:
                log.info("%s/%s: ok", group, name)
    log.info("cobertura: ctrl confiável desde %s, rounds desde %s, alvo/posição desde %s",
             answers["ctrl_reliable_from"], answers["rounds_reliable_from"], answers["target_reliable_from"])
    log.info("validação %s — relatórios em %s", "PASSOU" if ok else "FALHOU", out)
    return ok
