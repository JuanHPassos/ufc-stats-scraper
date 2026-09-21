"""Parser da página da luta + builders (junção card/página). Sem rede."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ufc_scraper.config import Settings
from ufc_scraper.parse import FIGHTS_COLUMNS, attribute_scores, build_events, build_fights
from ufc_scraper.parse.fights import parse_fight_summary
from ufc_scraper.paths import cache_path

S = Settings(date="2026-09-21")
FIXTURES = Path(__file__).parent / "fixtures"
TITLE = "568ec6af4008355a"


def summary(fixture, name):
    fid = name.rsplit("_", 1)[-1].removesuffix(".html")
    return parse_fight_summary(fixture(name), fid, S)


# -- parse_fight_summary ------------------------------------------------------


def test_udec_title_5_rounds(fixture):
    d = summary(fixture, f"fight_udec_title_5r_{TITLE}.html")
    assert (d["fighter_a_id"], d["fighter_b_id"]) == ("17e97649403ba428", "a0f0004aadf10b71")
    assert d["weight_class_raw"] == "UFC Flyweight Title Bout"
    assert (d["weight_class"], d["is_women"]) == ("Flyweight", False)
    assert d["time_format_raw"] == "5 Rnd (5-5-5-5-5)" and d["scheduled_rounds"] == 5
    assert d["total_fight_seconds"] == 1500
    assert d["referee"] == "Herb Dean"
    assert d["details_raw"] == "Sal D'amato 46 - 49. Derek Cleary 47 - 48. Ron McCarthy 45 - 50."
    assert d["judges_scores"] == [
        {"judge": "Sal D'amato", "score_1": 46, "score_2": 49},
        {"judge": "Derek Cleary", "score_1": 47, "score_2": 48},
        {"judge": "Ron McCarthy", "score_1": 45, "score_2": 50},
    ]
    c = d["check"]
    assert (c["winner_id"], c["result_type"], c["method"]) == ("17e97649403ba428", "win", "U-DEC")
    assert (c["end_round"], c["end_time_seconds"], c["is_title_fight"]) == (5, 300, True)
    assert c["details_free_text"] is None


def test_split_decision(fixture):
    d = summary(fixture, "fight_sdec_1aa008d8597a73b8.html")
    assert d["check"]["method"] == "S-DEC"
    assert [j["judge"] for j in d["judges_scores"]] == ["Andrew Topps", "Mike Bell", "Eric Colon"]


def test_ko_details_free_text_no_judges(fixture):
    d = summary(fixture, "fight_ko_bonus_fe612d20eec7ef35.html")
    assert d["check"]["method"] == "KO/TKO"
    assert d["judges_scores"] is None
    assert d["details_raw"] == "Elbow to Head In Clinch"
    assert d["check"]["details_free_text"] == "Elbow to Head In Clinch"
    assert d["total_fight_seconds"] == d["check"]["end_time_seconds"] + 300 * (d["check"]["end_round"] - 1)


def test_submission_two_line_detail(fixture):
    d = summary(fixture, "fight_sub_034c04e480d87b8f.html")
    assert d["check"]["method"] == "SUB"
    assert d["details_raw"] == "Rear Naked Choke One-arm RNC"
    assert d["scheduled_rounds"] == 5 and d["total_fight_seconds"] == 2 * 300 + 177


def test_draw_majority(fixture):
    d = summary(fixture, "fight_draw_mdec_a997593977ba8cad.html")
    assert d["check"]["result_type"] == "draw" and d["check"]["winner_id"] is None
    assert d["check"]["method"] == "M-DEC"
    assert d["judges_scores"][1] == {"judge": "Eric Colon", "score_1": 28, "score_2": 28}


def test_no_contest_with_reason(fixture):
    d = summary(fixture, "fight_nc_7e8749cbf32ef1f8.html")
    assert d["check"]["result_type"] == "no_contest" and d["check"]["method"] == "CNC"
    assert d["details_raw"] == "Low Blow from Sumudaerji"
    assert d["judges_scores"] is None
    assert d["total_fight_seconds"] == 300 + 105


def test_overturned_reason_and_scores_are_separated(fixture):
    d = summary(fixture, "fight_overturned_7ffdaa44fc8d111b.html")
    assert d["check"]["method"] == "OVERTURNED" and d["check"]["result_type"] == "no_contest"
    assert d["check"]["details_free_text"] == "Failed Drug Test by Idiris"
    assert [j["judge"] for j in d["judges_scores"]] == ["Ryan Thompson", "Sal D'amato", "Junichiro Kamijo"]
    assert d["details_raw"].startswith("Failed Drug Test by Idiris Ryan Thompson 29 - 28.")


def test_empty_page_gives_nulls_not_zeros():
    d = parse_fight_summary("<html></html>", "x" * 16, S)
    assert d["fighter_a_id"] is None and d["scheduled_rounds"] is None and d["total_fight_seconds"] is None
    assert d["judges_scores"] is None and d["referee"] is None


# -- attribute_scores ---------------------------------------------------------

J = [{"judge": "X", "score_1": 28, "score_2": 29}, {"judge": "Y", "score_1": 27, "score_2": 30}, {"judge": "Z", "score_1": 29, "score_2": 28}]


def test_attribute_scores_winner_is_a():
    out = attribute_scores(J, "A", "A", "B")
    assert [(j["score_a"], j["score_b"]) for j in out] == [(29, 28), (30, 27), (28, 29)]
    assert all(j["score_1"] == src["score_1"] for j, src in zip(out, J))  # ordem literal preservada


def test_attribute_scores_winner_is_b():
    out = attribute_scores(J, "B", "A", "B")
    assert [(j["score_a"], j["score_b"]) for j in out] == [(28, 29), (27, 30), (29, 28)]


def test_attribute_scores_draw_or_unknown_winner_is_null():
    assert all(j["score_a"] is None and j["score_b"] is None for j in attribute_scores(J, None, "A", "B"))
    assert all(j["score_a"] is None for j in attribute_scores(J, "ZZ", "A", "B"))
    assert attribute_scores(None, "A", "A", "B") is None
    assert attribute_scores([], "A", "A", "B") is None


# -- builders -----------------------------------------------------------------


@pytest.fixture
def raw_tree(tmp_path):
    """Monta data/raw/<date>/ com as fixtures (lista, 1 evento, 4 das suas lutas)."""
    s = Settings(data_dir=tmp_path, date="2026-09-21")

    def put(kind, key, name):
        p = cache_path(s, kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / name, p)

    put("events_list", None, "events_list.html")
    put("event", "8a0a35e7c74bebcc", "event_modern_8a0a35e7c74bebcc.html")
    put("fight", TITLE, f"fight_udec_title_5r_{TITLE}.html")
    put("fight", "fe612d20eec7ef35", "fight_ko_bonus_fe612d20eec7ef35.html")
    put("event", "5c38639f860a5542", "event_with_draw_5c38639f860a5542.html")
    put("fight", "a997593977ba8cad", "fight_draw_mdec_a997593977ba8cad.html")
    return s


def test_build_events(raw_tree):
    df = build_events(raw_tree)
    assert list(df.columns) == ["event_id", "name", "date", "location", "scraped_at", "source_url"]
    assert len(df) == 27 and df.event_id.is_unique
    assert (raw_tree.data_dir / "processed" / "2026-09-21" / "events.csv").exists()


def test_build_fights_merges_card_and_page(raw_tree, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        df = build_fights(raw_tree)
    assert list(df.columns) == FIGHTS_COLUMNS
    assert len(df) == 12 + 13 and df.fight_id.is_unique

    t = df.set_index("fight_id").loc[TITLE]
    assert t.fighter_order_source == "fight_page"
    assert t.weight_class_raw == "UFC Flyweight Title Bout" and bool(t.is_title_fight)
    assert t.referee == "Herb Dean" and t.scheduled_rounds == 5 and t.total_fight_seconds == 1500
    js = json.loads(t.judges_scores)
    assert js[0] == {"judge": "Sal D'amato", "score_1": 46, "score_2": 49, "score_a": 49, "score_b": 46}
    assert json.loads(t.bonuses) == ["fight_of_the_night"]

    d = df.set_index("fight_id").loc["a997593977ba8cad"]
    assert d.result_type == "draw" and pd.isna(d.winner_id)
    assert all(j["score_a"] is None for j in json.loads(d.judges_scores))

    # lutas sem página: campos da página nulos (não zero), ordem do card, WARNING
    missing = df[df.fighter_order_source == "card"]
    assert len(missing) == 25 - 3
    assert missing.referee.isna().all() and missing.scheduled_rounds.isna().all() and missing.judges_scores.isna().all()
    assert sum("página da luta ausente" in r.message for r in caplog.records) == 22
    assert not [r for r in caplog.records if "difere" in r.message]

    csv = pd.read_csv(raw_tree.data_dir / "processed" / "2026-09-21" / "fights.csv")
    assert len(csv) == 25 and csv.fight_id.is_unique


def test_cli_parse_runs_all_tables(raw_tree):
    import ufc_scraper.__main__ as cli

    argv = ["parse", "--date", "2026-09-21", "--data-dir", str(raw_tree.data_dir)]
    assert cli.main(argv) == 0
    out = raw_tree.data_dir / "processed" / "2026-09-21"
    assert (out / "events.csv").exists() and (out / "fights.csv").exists()
    assert cli.main(argv + ["--table", "fighters"]) == 0  # sem perfis salvos: tabela vazia, exit 0
