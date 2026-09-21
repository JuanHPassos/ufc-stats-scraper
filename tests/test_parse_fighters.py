"""Parser do perfil do lutador e da lista A–Z + builder. Sem rede."""

import logging
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ufc_scraper.config import Settings
from ufc_scraper.parse import build_fighters
from ufc_scraper.parse.fighters import FIGHTERS_COLUMNS, parse_fighter, parse_fighters_list
from ufc_scraper.paths import cache_path

S = Settings(date="2026-09-21")
FIXTURES = Path(__file__).parent / "fixtures"
VAN, PANTOJA = "17e97649403ba428", "a0f0004aadf10b71"


# -- perfil -------------------------------------------------------------------


def test_full_profile(fixture):
    r = parse_fighter(fixture(f"fighter_{VAN}.html"), VAN, S)
    assert list(r) == FIGHTERS_COLUMNS
    assert r == {
        "fighter_id": VAN, "name": "Joshua Van", "nickname": "The Fearless",
        "height_cm": 165.1, "weight_kg": 56.7, "reach_cm": 165.1, "stance": "Orthodox", "dob": "2001-10-10",
        "wins": 18, "losses": 2, "draws": 0, "nc": 0,
        "slpm": 8.26, "str_acc": 0.57, "sapm": 5.83, "str_def": 0.57,
        "td_avg": 0.7, "td_acc": 0.61, "td_def": 0.75, "sub_avg": 0.3,
        "scraped_at": "2026-09-21", "source_url": f"http://ufcstats.com/fighter-details/{VAN}",
    }


def test_second_profile(fixture):
    r = parse_fighter(fixture(f"fighter_{PANTOJA}.html"), PANTOJA, S)
    assert (r["name"], r["nickname"], r["dob"]) == ("Alexandre Pantoja", "The Cannibal", "1990-04-16")
    assert (r["wins"], r["losses"], r["draws"], r["nc"]) == (30, 7, 0, 0)
    assert r["reach_cm"] == 170.2


PROFILE = """
<html><body>
<h2><span class="b-content__title-highlight"> José   Aldo Jr. </span>
<span class="b-content__title-record"> Record: 31-8-0 (1 NC) </span></h2>
<p class="b-content__Nickname">   </p>
<ul>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Height:</i> -- </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Weight:</i> 145 lbs. </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Reach:</i> -- </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">STANCE:</i>  </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">DOB:</i> -- </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">SLpM:</i> 0.00 </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Str. Acc.:</i> 0% </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">SApM:</i> -- </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Str. Def:</i> 45% </li>
<li class="b-list__box-list-item"></li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">TD Avg.:</i> 1.5 </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">TD Acc.:</i> 33% </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">TD Def.:</i> 100% </li>
<li class="b-list__box-list-item"><i class="b-list__box-item-title">Sub. Avg.:</i> 0.0 </li>
</ul></body></html>
"""


def test_dashes_and_blank_fields_are_null_zero_stays_zero():
    r = parse_fighter(PROFILE, "c" * 16, S)
    assert r["name"] == "José Aldo Jr."  # acento e espaços extras tratados
    assert r["nickname"] is None
    assert (r["wins"], r["losses"], r["draws"], r["nc"]) == (31, 8, 0, 1)
    assert r["height_cm"] is None and r["reach_cm"] is None and r["dob"] is None and r["stance"] is None
    assert r["weight_kg"] == 65.8
    assert r["slpm"] == 0.0 and r["str_acc"] == 0.0  # zero é zero, não nulo
    assert r["sapm"] is None
    assert r["td_def"] == 1.0 and r["sub_avg"] == 0.0


def test_empty_page_gives_nulls_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        r = parse_fighter("<html></html>", "d" * 16, S)
    assert r["fighter_id"] == "d" * 16 and r["name"] is None and r["wins"] is None and r["height_cm"] is None
    assert any("perfil sem nome" in m.message for m in caplog.records)


def test_unknown_label_warns_but_does_not_break(caplog):
    html = PROFILE.replace("Sub. Avg.:", "Novo Campo:")
    with caplog.at_level(logging.WARNING):
        r = parse_fighter(html, "e" * 16, S)
    assert r["sub_avg"] is None and r["td_def"] == 1.0
    assert any("rótulos desconhecidos" in m.message and "Novo Campo" in m.message for m in caplog.records)


def test_invalid_value_warns_and_nulls(caplog):
    html = PROFILE.replace("145 lbs.", "sessenta quilos")
    with caplog.at_level(logging.WARNING):
        r = parse_fighter(html, "f" * 16, S)
    assert r["weight_kg"] is None
    assert any("peso inválido" in m.message for m in caplog.records)


# -- lista A–Z ----------------------------------------------------------------


def test_fighters_list(fixture):
    rows = parse_fighters_list(fixture("fighters_list_x.html"), S)
    assert len(rows) == 4  # cada lutador aparece 3x (nome, sobrenome, apelido): deduplicado
    assert rows[0] == {"fighter_id": "e6dac752a2418a88", "name": "Rubens Xavier", "nickname": "Macula"}
    assert rows[1]["name"] == "Xiao Long" and rows[1]["nickname"] is None
    assert len({r["fighter_id"] for r in rows}) == 4


def test_fighters_list_empty():
    assert parse_fighters_list("<html><table><tbody></tbody></table></html>", S) == []


# -- builder ------------------------------------------------------------------


@pytest.fixture
def raw_tree(tmp_path):
    s = Settings(data_dir=tmp_path, date="2026-09-21")
    for key, name in [(VAN, f"fighter_{VAN}.html"), (PANTOJA, f"fighter_{PANTOJA}.html")]:
        p = cache_path(s, "fighter", key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / name, p)
    p = cache_path(s, "fighters_list", "x")
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "fighters_list_x.html", p)
    return s


def test_build_fighters_and_coverage_warning(raw_tree, caplog):
    with caplog.at_level(logging.WARNING):
        df = build_fighters(raw_tree)
    assert list(df.columns) == FIGHTERS_COLUMNS
    assert len(df) == 2 and df.fighter_id.is_unique
    assert str(df.wins.dtype) == "Int64" and (df.nc == 0).all()
    # os 4 da letra x não têm perfil salvo -> 4 WARNINGs de cobertura
    missing = [m for m in caplog.records if "não tem perfil salvo" in m.message]
    assert len(missing) == 4 and any("Rubens Xavier" in m.message for m in missing)
    csv = pd.read_csv(raw_tree.data_dir / "processed" / "2026-09-21" / "fighters.csv")
    assert set(csv.name) == {"Joshua Van", "Alexandre Pantoja"}
    assert csv.dob.str.match(r"\d{4}-\d{2}-\d{2}").all()


def test_cli_parse_fighters(raw_tree):
    import ufc_scraper.__main__ as cli

    assert cli.main(["parse", "--date", "2026-09-21", "--data-dir", str(raw_tree.data_dir), "--table", "fighters"]) == 0
