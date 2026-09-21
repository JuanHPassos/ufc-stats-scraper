import logging

import pandas as pd
import pytest

from ufc_scraper.sample import era_of, manual_check_template, render_fight, sample_fights


def fights_and_events(years: dict[int, int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`years`: ano -> nº de lutas. Um evento por ano."""
    ev, fi = [], []
    for year, n in years.items():
        eid = f"{year:016d}"
        ev.append({"event_id": eid, "name": f"UFC {year}", "date": f"{year}-06-01", "location": "x"})
        for i in range(n):
            fid = f"{year:04d}{i:012d}"
            fi.append({"fight_id": fid, "event_id": eid, "fighter_a_id": "a" * 16, "fighter_b_id": "b" * 16,
                       "method": "U-DEC", "source_url": f"http://ufcstats.com/fight-details/{fid}"})
    return pd.DataFrame(fi), pd.DataFrame(ev)


@pytest.mark.parametrize("year, era", [(1993, "pre-2005"), (2004, "pre-2005"), (2005, "2005-2015"), (2015, "2005-2015"), (2016, "2016+"), (2026, "2016+"), (None, None)])
def test_era_of(year, era):
    assert era_of(year) == era


def test_sample_is_stratified_and_deterministic():
    f, e = fights_and_events({1995: 20, 2010: 20, 2020: 20})
    s1 = sample_fights(f, e, n=10, seed=42)
    s2 = sample_fights(f, e, n=10, seed=42)
    assert len(s1) == 10 and s1.fight_id.is_unique
    assert s1.fight_id.tolist() == s2.fight_id.tolist()  # determinístico
    counts = s1.era.value_counts()
    assert (counts >= 2).all() and set(counts.index) == {"pre-2005", "2005-2015", "2016+"}
    assert sample_fights(f, e, n=10, seed=7).fight_id.tolist() != s1.fight_id.tolist()
    assert {"year", "era", "event_name", "date"} <= set(s1.columns)


def test_sample_rotates_remainder_between_eras():
    f, e = fights_and_events({1995: 20, 2010: 20, 2020: 20})
    s = sample_fights(f, e, n=9, seed=1)
    assert s.era.value_counts().tolist() == [3, 3, 3]


def test_sample_with_missing_era_warns_and_takes_what_exists(caplog):
    f, e = fights_and_events({2020: 20, 2024: 1})
    with caplog.at_level(logging.WARNING):
        s = sample_fights(f, e, n=10, seed=42)
    assert len(s) == 10 and set(s.era) == {"2016+"}
    assert sum("cota mínima" in r.message for r in caplog.records) == 2  # pre-2005 e 2005-2015 vazias


def test_sample_fewer_fights_than_requested(caplog):
    f, e = fights_and_events({1995: 3})
    with caplog.at_level(logging.WARNING):
        s = sample_fights(f, e, n=10, seed=42)
    assert len(s) == 3
    assert any("só 3 luta(s) disponíveis" in r.message for r in caplog.records)


def test_sample_empty():
    f, e = fights_and_events({})
    assert sample_fights(f, e).empty


def test_render_fight_and_template():
    f, e = fights_and_events({2020: 2})
    s = sample_fights(f, e, n=2, seed=0)
    row = s.iloc[0]
    fs = pd.DataFrame([{"fight_id": row.fight_id, "fighter_id": "a" * 16, "kd": 1, "scraped_at": "x", "source_url": "y"}])
    rs = pd.DataFrame(columns=["fight_id", "fighter_id", "round", "kd"])
    text = render_fight(row, fs, rs)
    assert row.source_url in text and "fight_stats:" in text and "kd" in text and "(sem rounds)" in text
    assert "scraped_at" not in text.split("fight_stats:")[1]  # colunas de proveniência omitidas nas stats
    empty = render_fight(row, fs.iloc[0:0], rs)
    assert "esperado em lutas antigas" in empty

    tpl = manual_check_template(s)
    assert tpl.count("\n| ") == 2 + 2  # cabeçalho + separador + 2 lutas
    assert f"`{row.fight_id}`" in tpl and "seed 42" in tpl
