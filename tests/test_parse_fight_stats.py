"""Parser das tabelas de estatísticas (totais e por round) + builders. Sem rede."""

import logging
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ufc_scraper.config import Settings
from ufc_scraper.parse import FIGHT_STATS_COLUMNS, ROUND_STATS_COLUMNS, build_fight_stats, build_round_stats
from ufc_scraper.parse.fight_stats import TOTALS_COLUMNS, parse_round_totals, parse_totals
from ufc_scraper.paths import cache_path

S = Settings(date="2026-09-21")
FIXTURES = Path(__file__).parent / "fixtures"
TITLE = "568ec6af4008355a"
VAN, PANTOJA = "17e97649403ba428", "a0f0004aadf10b71"


def strip(rec):
    return {k: v for k, v in rec.items() if k not in ("scraped_at", "source_url")}


# -- totais -------------------------------------------------------------------


def test_totals_5_round_title_fight(fixture):
    rows = parse_totals(fixture(f"fight_udec_title_5r_{TITLE}.html"), TITLE, S)
    assert len(rows) == 2
    assert all(r["fight_id"] == TITLE and r["scraped_at"] == "2026-09-21" for r in rows)
    assert all(r["source_url"] == f"http://ufcstats.com/fight-details/{TITLE}" for r in rows)
    # valores conferidos a olho na fixture: "181 of 305", "259 of 392", "0 of 0", ctrl 2:13
    assert strip(rows[0]) == {
        "fight_id": TITLE, "fighter_id": VAN, "kd": 1,
        "sig_str_landed": 181, "sig_str_attempted": 305,
        "total_str_landed": 259, "total_str_attempted": 392,
        "td_landed": 0, "td_attempted": 0, "sub_att": 1, "rev": 1, "ctrl_seconds": 133,
    }
    assert strip(rows[1]) == {
        "fight_id": TITLE, "fighter_id": PANTOJA, "kd": 0,
        "sig_str_landed": 147, "sig_str_attempted": 284,
        "total_str_landed": 159, "total_str_attempted": 300,
        "td_landed": 5, "td_attempted": 18, "sub_att": 0, "rev": 0, "ctrl_seconds": 551,
    }


def test_totals_ordered_like_persons_on_page(fixture):
    from ufc_scraper.parse.fights import parse_fight_summary

    html = fixture("fight_sdec_1aa008d8597a73b8.html")
    summary = parse_fight_summary(html, "1aa008d8597a73b8", S)
    rows = parse_totals(html, "1aa008d8597a73b8", S)
    assert [r["fighter_id"] for r in rows] == [summary["fighter_a_id"], summary["fighter_b_id"]]


def test_totals_no_percent_columns(fixture):
    rows = parse_totals(fixture(f"fight_udec_title_5r_{TITLE}.html"), TITLE, S)
    assert not any("pct" in k or "%" in k for k in rows[0])
    assert set(rows[0]) == {"fight_id", "fighter_id", "scraped_at", "source_url", *TOTALS_COLUMNS}


def test_page_without_tables_returns_empty_not_zeros():
    assert parse_totals("<html><body>Sem estatísticas</body></html>", "x" * 16, S) == []
    assert parse_round_totals("<html></html>", "x" * 16, S) == []


# -- por round ----------------------------------------------------------------


def test_round_totals_5_rounds_sum_to_totals(fixture):
    html = fixture(f"fight_udec_title_5r_{TITLE}.html")
    rounds = parse_round_totals(html, TITLE, S)
    totals = parse_totals(html, TITLE, S)
    assert len(rounds) == 10
    assert sorted({r["round"] for r in rounds}) == [1, 2, 3, 4, 5]
    assert [r["fighter_id"] for r in rounds[:2]] == [VAN, PANTOJA]
    r1_van = next(r for r in rounds if r["round"] == 1 and r["fighter_id"] == VAN)
    assert (r1_van["sig_str_landed"], r1_van["sig_str_attempted"], r1_van["ctrl_seconds"]) == (13, 27, 45)
    for t in totals:
        mine = [r for r in rounds if r["fighter_id"] == t["fighter_id"]]
        for col in TOTALS_COLUMNS:
            assert sum(r[col] for r in mine) == t[col], col


def test_round_totals_1_round_ko(fixture):
    rounds = parse_round_totals(fixture("fight_ko_bonus_fe612d20eec7ef35.html"), "fe612d20eec7ef35", S)
    assert len(rounds) == 2 and {r["round"] for r in rounds} == {1}


def test_round_totals_3_rounds_split_decision(fixture):
    rounds = parse_round_totals(fixture("fight_sdec_1aa008d8597a73b8.html"), "1aa008d8597a73b8", S)
    assert len(rounds) == 6 and {r["round"] for r in rounds} == {1, 2, 3}


# -- valores nulos e páginas estranhas -----------------------------------------

TOTALS_HTML = """
<table><thead><tr>{ths}</tr></thead><tbody><tr>
<td><p><a href="http://ufcstats.com/fighter-details/aaaaaaaaaaaaaaaa">A</a></p><p><a href="http://ufcstats.com/fighter-details/bbbbbbbbbbbbbbbb">B</a></p></td>
<td><p>1</p><p>--</p></td>
<td><p>10 of 20</p><p>--</p></td>
<td><p>50%</p><p>---</p></td>
<td><p>12 of 25</p><p>--</p></td>
<td><p>0 of 1</p><p>--</p></td>
<td><p>---</p><p>---</p></td>
<td><p>0</p><p>--</p></td>
<td><p>0</p><p>--</p></td>
<td><p>--</p><p>1:05</p></td>
</tr></tbody></table>
"""
HEADS = ["Fighter", "KD", "Sig. str.", "Sig. str. %", "Total str.", "Td", "Td %", "Sub. att", "Rev.", "Ctrl"]


def test_dashes_become_none_not_zero():
    html = TOTALS_HTML.format(ths="".join(f"<th>{h}</th>" for h in HEADS))
    a, b = parse_totals(html, "f" * 16, S)
    assert a["kd"] == 1 and a["ctrl_seconds"] is None and (a["sig_str_landed"], a["sig_str_attempted"]) == (10, 20)
    assert b["fighter_id"] == "b" * 16
    assert all(b[c] is None for c in TOTALS_COLUMNS if c != "ctrl_seconds") and b["ctrl_seconds"] == 65


def test_site_header_bug_td_pct_is_tolerated():
    heads = HEADS.copy()
    heads[5] = "Td %"  # bug real do site na tabela por round
    html = TOTALS_HTML.format(ths="".join(f"<th>{h}</th>" for h in heads))
    assert len(parse_totals(html, "f" * 16, S)) == 2


def test_unexpected_column_count_warns_and_skips(caplog):
    html = TOTALS_HTML.format(ths="".join(f"<th>{h}</th>" for h in HEADS)).replace("<td><p>0</p><p>--</p></td>\n<td><p>--</p><p>1:05</p></td>", "")
    with caplog.at_level(logging.WARNING):
        rows = parse_totals(html, "f" * 16, S)
    assert rows == []
    assert any("colunas na tabela" in r.message for r in caplog.records)


# -- builders -----------------------------------------------------------------


@pytest.fixture
def raw_tree(tmp_path):
    s = Settings(data_dir=tmp_path, date="2026-09-21")
    for key, name in [
        (TITLE, f"fight_udec_title_5r_{TITLE}.html"),
        ("fe612d20eec7ef35", "fight_ko_bonus_fe612d20eec7ef35.html"),
        ("1aa008d8597a73b8", "fight_sdec_1aa008d8597a73b8.html"),
    ]:
        p = cache_path(s, "fight", key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / name, p)
    p = cache_path(s, "fight", "0" * 16)
    p.write_text("<html><body>luta antiga sem estatísticas</body></html>", encoding="utf-8")
    return s


def test_build_fight_stats_and_round_stats(raw_tree):
    fs = build_fight_stats(raw_tree)
    rs = build_round_stats(raw_tree)
    assert list(fs.columns) == FIGHT_STATS_COLUMNS and list(rs.columns) == ROUND_STATS_COLUMNS
    assert len(fs) == 6 and len(rs) == 10 + 2 + 6  # a luta sem tabela não gera linhas
    assert "0" * 16 not in set(fs.fight_id)
    assert not fs.duplicated(["fight_id", "fighter_id"]).any()
    assert not rs.duplicated(["fight_id", "fighter_id", "round"]).any()
    assert str(fs.kd.dtype) == "Int64" and str(rs["round"].dtype) == "Int64"
    out = raw_tree.data_dir / "processed" / "2026-09-21"
    csv = pd.read_csv(out / "fight_stats.csv")
    assert len(csv) == 6 and csv.ctrl_seconds.notna().all()
    assert (out / "round_stats.csv").exists()


def test_cli_parse_stats_tables(raw_tree):
    import ufc_scraper.__main__ as cli

    argv = ["parse", "--date", "2026-09-21", "--data-dir", str(raw_tree.data_dir)]
    assert cli.main(argv + ["--table", "fight_stats"]) == 0
    assert cli.main(argv + ["--table", "round_stats"]) == 0
