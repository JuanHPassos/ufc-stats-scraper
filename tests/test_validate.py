"""Checagens da spec §7 sobre DataFrames sintéticos: um caso passando e um falhando por checagem."""

import pandas as pd
import pytest

from ufc_scraper import validate as v

A, B, C, D = "a" * 16, "b" * 16, "c" * 16, "d" * 16
E1, F1, F2 = "e" * 16, "1" * 16, "2" * 16
STAT_COLS = v.ROUND_SUM_COLUMNS


def stats_row(fight_id, fighter_id, sig=10, total=12, **over):
    r = {
        "fight_id": fight_id, "fighter_id": fighter_id, "kd": 0,
        "sig_str_landed": sig, "sig_str_attempted": sig + 5, "total_str_landed": total, "total_str_attempted": total + 5,
        "td_landed": 1, "td_attempted": 2, "sub_att": 0, "rev": 0, "ctrl_seconds": 30,
        "head_landed": sig - 3, "head_attempted": sig + 1, "body_landed": 2, "body_attempted": 2, "leg_landed": 1, "leg_attempted": 2,
        "distance_landed": sig - 1, "distance_attempted": sig + 3, "clinch_landed": 1, "clinch_attempted": 1, "ground_landed": 0, "ground_attempted": 1,
    }
    r.update(over)
    return r


def good_tables() -> v.Tables:
    events = pd.DataFrame([{"event_id": E1, "name": "UFC X", "date": "2024-05-04", "location": "Rio"}])
    fights = pd.DataFrame([
        {"fight_id": F1, "event_id": E1, "fighter_a_id": A, "fighter_b_id": B, "winner_id": A, "result_type": "win",
         "method": "U-DEC", "went_to_decision": True, "end_round": 3, "scheduled_rounds": 3, "total_fight_seconds": 900,
         "referee": "Herb Dean", "judges_scores": "[]"},
        {"fight_id": F2, "event_id": E1, "fighter_a_id": C, "fighter_b_id": D, "winner_id": None, "result_type": "draw",
         "method": "M-DEC", "went_to_decision": True, "end_round": 3, "scheduled_rounds": 3, "total_fight_seconds": 900,
         "referee": "Marc Goddard", "judges_scores": "[]"},
    ])
    fight_stats = pd.DataFrame([stats_row(F1, A), stats_row(F1, B), stats_row(F2, C), stats_row(F2, D)])
    # 3 rounds por lutador cuja soma bate com os totais: round 1 leva tudo, 2 e 3 zerados
    rows = []
    for _, t in fight_stats.iterrows():
        rows.append({**{k: t[k] for k in ["fight_id", "fighter_id", *STAT_COLS]}, "round": 1})
        for r in (2, 3):
            rows.append({"fight_id": t.fight_id, "fighter_id": t.fighter_id, "round": r, **{c: 0 for c in STAT_COLS}})
    round_stats = pd.DataFrame(rows)
    fighters = pd.DataFrame([{"fighter_id": x, "name": x[0].upper()} for x in (A, B, C, D)])
    return v.Tables(events, fights, fight_stats, round_stats, fighters, raw_event_ids={E1}, card_fight_ids={E1: [F1, F2]})


ALL_CHECKS = v.INTEGRITY + v.CONSISTENCY


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_good_tables_pass_every_check(check):
    assert check(good_tables()) == []


def test_run_checks_groups_and_passes():
    results = v.run_checks(good_tables())
    assert set(results) == {"integridade", "consistência"}
    assert all(not viol for group in results.values() for viol in group.values())


# -- um caso falhando por checagem --------------------------------------------


def test_events_without_html():
    t = good_tables()
    t.raw_event_ids = set()  # sem info do disco: não checa
    assert v.check_events_have_html(t) == []
    t.raw_event_ids = {"f" * 16}
    out = v.check_events_have_html(t)
    assert len(out) == 1 and E1 in out[0] and "1" in out[0]


def test_fights_cover_cards():
    t = good_tables()
    t.card_fight_ids[E1].append("9" * 16)
    assert any("ausentes em fights" in m for m in v.check_fights_cover_cards(t))
    t = good_tables()
    t.fights.loc[0, "event_id"] = "0" * 16
    assert any("fora de events" in m for m in v.check_fights_cover_cards(t))


def test_fighters_exist():
    t = good_tables()
    t.fighters = t.fighters[t.fighters.fighter_id != D]
    out = v.check_fighters_exist(t)
    assert len(out) == 1 and D in out[0]


def test_unique_pks_duplicate_and_null():
    t = good_tables()
    t.fight_stats = pd.concat([t.fight_stats, t.fight_stats.iloc[[0]]])
    assert any("fight_stats" in m and "duplicada" in m for m in v.check_unique_pks(t))
    t = good_tables()
    t.fighters.loc[0, "fighter_id"] = None
    assert any("fighters" in m and "nulo" in m for m in v.check_unique_pks(t))


def test_landed_le_attempted():
    t = good_tables()
    t.round_stats.loc[0, "td_landed"] = 99
    out = v.check_landed_le_attempted(t)
    assert len(out) == 1 and "round_stats.td" in out[0]


def test_sig_le_total():
    t = good_tables()
    t.fight_stats.loc[1, "sig_str_landed"] = 100
    out = v.check_sig_le_total(t)
    assert any("fight_stats: sig_str_landed > total_str_landed" in m for m in out)


def test_sig_breakdown_sums():
    t = good_tables()
    t.fight_stats.loc[0, "head_landed"] = 0
    out = v.check_sig_breakdown_sums(t)
    assert len(out) == 1 and "head+body+leg_landed" in out[0]
    # nulos não são violação
    t = good_tables()
    t.fight_stats.loc[0, ["head_landed", "body_landed", "leg_landed"]] = None
    assert v.check_sig_breakdown_sums(t) == []


def test_round_sums():
    t = good_tables()
    t.round_stats.loc[1, "kd"] = 5  # round 2 do lutador A
    out = v.check_round_sums(t)
    assert len(out) == 1 and "soma de kd" in out[0] and f"{F1}/{A}" in out[0]
    t = good_tables()
    t.fight_stats = t.fight_stats.iloc[1:]
    assert any("sem linha em fight_stats" in m for m in v.check_round_sums(t))
    t = good_tables()
    t.round_stats = t.round_stats.iloc[0:0]
    assert v.check_round_sums(t) == []  # sem rounds, nada a comparar


def test_rounds_vs_fight():
    t = good_tables()
    t.fights.loc[0, "end_round"] = 4
    assert any("end_round > scheduled_rounds" in m for m in v.check_rounds_vs_fight(t))
    t = good_tables()
    t.fights.loc[0, "end_round"] = 2  # round_stats tem round 3
    assert any("round > end_round" in m for m in v.check_rounds_vs_fight(t))


def test_ctrl_le_duration():
    t = good_tables()
    t.fight_stats.loc[0, "ctrl_seconds"] = 901
    out = v.check_ctrl_le_duration(t)
    assert len(out) == 1 and f"{F1}/{A}" in out[0]


def test_winner_and_result():
    t = good_tables()
    t.fights.loc[0, "winner_id"] = "z" * 16
    assert any("não é A nem B" in m for m in v.check_winner_and_result(t))
    t = good_tables()
    t.fights.loc[0, "winner_id"] = None
    assert any("win sem winner_id" in m for m in v.check_winner_and_result(t))
    t = good_tables()
    t.fights.loc[1, "winner_id"] = C
    assert any("empate/NC com winner_id" in m for m in v.check_winner_and_result(t))
    t = good_tables()
    t.fights.loc[0, "fighter_b_id"] = A
    assert any("fighter_a_id == fighter_b_id" in m for m in v.check_winner_and_result(t))


def test_decision_flag():
    t = good_tables()
    t.fights.loc[0, "went_to_decision"] = False
    out = v.check_decision_flag(t)
    assert len(out) == 1 and F1 in out[0]


def test_stats_fighters_belong_to_fight():
    t = good_tables()
    t.fight_stats.loc[0, "fighter_id"] = C  # C não luta em F1
    out = v.check_stats_fighters_belong_to_fight(t)
    assert len(out) == 1 and "fight_stats" in out[0]


def test_examples_are_truncated():
    t = good_tables()
    t.fighters = t.fighters.iloc[0:0]
    t.fights = pd.concat([t.fights.assign(fight_id=[f"{i:016x}" for i in range(2 * k, 2 * k + 2)], fighter_a_id=[f"{i:016x}" for i in range(100 + 2 * k, 102 + 2 * k)]) for k in range(15)])
    out = v.check_fighters_exist(t)
    assert "(+" in out[0] and out[0].count(",") == v.MAX_EXAMPLES - 1


# -- cobertura ----------------------------------------------------------------


def test_order_informative_from():
    cov = pd.DataFrame({"year": [2008, 2009, 2010, 2011], "pct_winner_is_a": [100.0, 100.0, 61.2, 59.7]})
    assert v.order_informative_from(cov) == 2010  # deixa de ser "vencedor primeiro"
    # nunca foi vencedor-primeiro: informativa desde o começo
    assert v.order_informative_from(pd.DataFrame({"year": [2015, 2016], "pct_winner_is_a": [55.0, 57.0]})) == 2015
    # sempre vencedor-primeiro: não há ano informativo
    assert v.order_informative_from(pd.DataFrame({"year": [1995, 1996], "pct_winner_is_a": [100.0, 100.0]})) is None
    assert v.order_informative_from(pd.DataFrame(columns=["year"])) is None


def test_coverage_includes_winner_is_a():
    t = good_tables()  # F1: A vence; F2: empate (não conta)
    cov = v.coverage_by_year(t)
    assert cov.pct_winner_is_a.iloc[0] == 100.0


def test_coverage_by_year_and_reliable_from():
    t = good_tables()
    cov = v.coverage_by_year(t)
    assert cov.year.tolist() == [2024] and cov.fights.iloc[0] == 2
    assert cov.pct_fight_stats.iloc[0] == 100 and cov.pct_ctrl.iloc[0] == 100
    assert v.reliable_from(cov, "pct_ctrl") == 2024

    cov = pd.DataFrame({"year": [1995, 2000, 2001, 2005], "pct_ctrl": [0, 100, 90, 100]})
    assert v.reliable_from(cov, "pct_ctrl") == 2005  # 2001 regrediu: só a partir de 2005
    assert v.reliable_from(pd.DataFrame({"year": [2000], "pct_ctrl": [50]}), "pct_ctrl") is None
    assert v.reliable_from(pd.DataFrame(columns=["year", "pct_ctrl"]), "pct_ctrl") is None


def test_reports_are_written(tmp_path):
    t = good_tables()
    ok = v.write_validation_report(v.run_checks(t), t, tmp_path / "validation_report.md")
    assert ok is True
    text = (tmp_path / "validation_report.md").read_text(encoding="utf-8")
    assert "PASSOU" in text and "check_round_sums" in text and "❌" not in text
    answers = v.write_coverage_report(t, tmp_path / "coverage_report.md")
    assert answers["ctrl_reliable_from"] == 2024
    assert "order_informative_from" in answers and "judges_reliable_from" in answers
    assert "vencedor primeiro" in (tmp_path / "coverage_report.md").read_text(encoding="utf-8")
    assert "U-DEC" in (tmp_path / "coverage_report.md").read_text(encoding="utf-8")


def test_run_validation_end_to_end(tmp_path):
    """Pipeline real: fixtures -> parse -> validate (deve FALHAR: faltam perfis e páginas)."""
    import shutil
    from pathlib import Path

    from ufc_scraper.config import Settings
    from ufc_scraper.parse import BUILDERS
    from ufc_scraper.paths import cache_path

    s = Settings(data_dir=tmp_path, date="2026-09-21")
    fx = Path(__file__).parent / "fixtures"
    for kind, key, name in [
        ("events_list", None, "events_list.html"),
        ("event", "8a0a35e7c74bebcc", "event_modern_8a0a35e7c74bebcc.html"),
        ("fight", "568ec6af4008355a", "fight_udec_title_5r_568ec6af4008355a.html"),
        ("fighter", "17e97649403ba428", "fighter_17e97649403ba428.html"),
        ("fighter", "a0f0004aadf10b71", "fighter_a0f0004aadf10b71.html"),
    ]:
        p = cache_path(s, kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fx / name, p)
    for build in BUILDERS.values():
        build(s)
    assert v.run_validation(s) is False
    report = (tmp_path / "processed" / "2026-09-21" / "validation_report.md").read_text(encoding="utf-8")
    assert "FALHOU" in report and "eventos sem HTML" in report and "sem perfil" in report
    assert "| `check_round_sums` | ✅ |" in report  # o que existe é consistente
    assert (tmp_path / "processed" / "2026-09-21" / "coverage_report.md").exists()
