"""Regressão das eras antigas (1994–2001), com fixtures reais da coleta completa.

Casos que só existem no começo do UFC: torneios de uma noite, `No Time Limit`,
rounds de 20 min, lutas sem tabela de estatísticas, perfis sem altura/DOB e
categorias em que o card e a página da luta discordam.
"""

import shutil
from pathlib import Path

import pytest

from ufc_scraper.config import Settings
from ufc_scraper.parse import build_fights
from ufc_scraper.parse.events import parse_event_card
from ufc_scraper.parse.fight_stats import parse_round_totals, parse_totals
from ufc_scraper.parse.fighters import parse_fighter
from ufc_scraper.parse.fights import parse_fight_summary
from ufc_scraper.paths import cache_path

S = Settings(date="2026-09-21")
FIXTURES = Path(__file__).parent / "fixtures"
UFC2 = "a6a9ab5a824e8f66"
TOURNEY, NO_STATS, DIVERGENCE = "00835554f95fa911", "8e03db41687d9132", "f32f823658478705"
SPARSE = "02d808afb96669de"


def by_id(rows, fight_id):
    return next(r for r in rows if r["fight_id"] == fight_id)


# -- card antigo --------------------------------------------------------------


def test_ufc2_card(fixture):
    rows = parse_event_card(fixture(f"event_old_ufc2_{UFC2}.html"), UFC2, S)
    assert len(rows) == 15  # torneio de uma noite: mais lutas que um card moderno
    r = by_id(rows, TOURNEY)
    assert (r["weight_class"], r["is_title_fight"], r["is_women"]) == ("Open Weight", True, False)
    assert (r["method"], r["end_round"], r["end_time_seconds"]) == ("KO/TKO", 1, 77)
    assert r["result_type"] == "win" and r["winner_id"]


# -- formatos de tempo antigos ------------------------------------------------


@pytest.mark.parametrize(
    "name, fight_id, fmt, rounds, total",
    [
        ("fight_old_tournament_title", TOURNEY, "No Time Limit", None, 77),
        ("fight_old_no_stats", NO_STATS, "1 Rnd (20)", 1, 186),
        ("fight_old_wc_divergence", DIVERGENCE, "1 Rnd + 2OT (15-3-3)", 3, 22),  # 1 regular + 2 OT
    ],
)
def test_old_time_formats(fixture, name, fight_id, fmt, rounds, total):
    d = parse_fight_summary(fixture(f"{name}_{fight_id}.html"), fight_id, S)
    assert d["time_format_raw"] == fmt
    assert d["scheduled_rounds"] == rounds  # None em "No Time Limit"
    # sempre termina no 1º round nessas eras: total == tempo do round, sem somar anteriores
    assert d["check"]["end_round"] == 1 and d["total_fight_seconds"] == total == d["check"]["end_time_seconds"]


# -- luta sem tabela de estatísticas ------------------------------------------


def test_fight_without_stats_tables_returns_empty(fixture):
    html = fixture(f"fight_old_no_stats_{NO_STATS}.html")
    assert parse_totals(html, NO_STATS, S) == []
    assert parse_round_totals(html, NO_STATS, S) == []
    d = parse_fight_summary(html, NO_STATS, S)
    assert d["referee"] == "John McCarthy" and d["check"]["method"] == "KO/TKO"  # o resumo existe


def test_fight_with_stats_in_the_90s(fixture):
    """Nem toda luta antiga é sem estatísticas: esta tem as duas tabelas."""
    rows = parse_totals(fixture(f"fight_old_tournament_title_{TOURNEY}.html"), TOURNEY, S)
    assert len(rows) == 2 and rows[0]["sig_str_landed"] is not None
    assert len(parse_round_totals(fixture(f"fight_old_tournament_title_{TOURNEY}.html"), TOURNEY, S)) == 2


# -- categoria: torneio sem peso e divergência card/página --------------------


def test_tournament_title_page_has_no_weight_class(fixture):
    """"UFC 2 Tournament Title Bout" não é categoria de peso; o card ("Open Weight") é a fonte."""
    d = parse_fight_summary(fixture(f"fight_old_tournament_title_{TOURNEY}.html"), TOURNEY, S)
    assert d["weight_class_raw"] == "UFC 2 Tournament Title Bout"
    assert d["weight_class"] not in ("Open Weight",)  # a página sozinha não sabe o peso
    assert d["check"]["is_title_fight"] is True


def test_merge_uses_card_when_page_has_no_weight_class(tmp_path, fixture):
    s = Settings(data_dir=tmp_path, date="2026-09-21")
    for kind, key, name in [("event", UFC2, f"event_old_ufc2_{UFC2}.html"),
                            ("fight", TOURNEY, f"fight_old_tournament_title_{TOURNEY}.html")]:
        p = cache_path(s, kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / name, p)
    df = build_fights(s).set_index("fight_id")
    r = df.loc[TOURNEY]
    assert r.weight_class == "Open Weight"        # do card
    assert r.weight_class_card == "Open Weight"
    assert r.weight_class_raw == "UFC 2 Tournament Title Bout"  # da página, com o tipo de título
    assert bool(r.is_title_fight) is True
    assert r.scheduled_rounds is None or str(r.scheduled_rounds) == "<NA>"


def test_merge_keeps_both_when_card_and_page_disagree(tmp_path, fixture, caplog):
    """UFC 16 (1998): página diz Light Heavyweight, card diz Middleweight (divisões renomeadas)."""
    import logging

    s = Settings(data_dir=tmp_path, date="2026-09-21")
    event_id = "e" * 16
    # card sintético com a luta real, para exercitar o merge sem baixar o evento inteiro
    card = f'''<table><tr class="b-fight-details__table-row" data-link="http://ufcstats.com/fight-details/{DIVERGENCE}">
      <td><p><a class="b-flag"><i class="b-flag__text">win</i></a></p></td>
      <td><p><a href="http://ufcstats.com/fighter-details/fcaae0385b514f11">A</a></p>
          <p><a href="http://ufcstats.com/fighter-details/{"b" * 16}">B</a></p></td>
      <td><p>0</p><p>0</p></td><td><p>0</p><p>0</p></td><td><p>0</p><p>0</p></td><td><p>0</p><p>0</p></td>
      <td><p>Middleweight</p></td><td><p>KO/TKO</p><p></p></td><td><p>1</p></td><td><p>0:22</p></td>
    </tr></table>'''
    p = cache_path(s, "event", event_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(card, encoding="utf-8")
    p = cache_path(s, "fight", DIVERGENCE)
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / f"fight_old_wc_divergence_{DIVERGENCE}.html", p)

    with caplog.at_level(logging.WARNING):
        df = build_fights(s).set_index("fight_id")
    r = df.loc[DIVERGENCE]
    assert r.weight_class == "Light Heavyweight"   # página
    assert r.weight_class_card == "Middleweight"   # card preservado para a análise
    assert r.weight_class_raw == "UFC Light Heavyweight Title Bout"
    assert any("categoria página=" in m.message and "weight_class_card" in m.message for m in caplog.records)


# -- perfil antigo com campos ausentes ----------------------------------------


def test_sparse_fighter_profile(fixture):
    r = parse_fighter(fixture(f"fighter_sparse_{SPARSE}.html"), SPARSE, S)
    assert r["name"] == "Alex Zuniga"
    # "--" no site vira nulo, nunca zero
    assert r["height_cm"] is None and r["reach_cm"] is None and r["dob"] is None and r["stance"] is None
    assert r["weight_kg"] == 65.8  # o que existe é convertido
    assert (r["wins"], r["losses"], r["draws"], r["nc"]) == (6, 3, 0, 0)
    # estatísticas de carreira zeradas são zero de verdade (lutou antes de existir registro)
    assert r["slpm"] == 0.0 and r["str_acc"] == 0.0 and r["sub_avg"] == 0.0
