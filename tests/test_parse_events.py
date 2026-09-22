"""Parser da lista de eventos e do card (fixtures reais). Sem rede."""

import pytest

from ufc_scraper.config import Settings
from ufc_scraper.parse.events import EVENTS_COLUMNS, parse_event_card, parse_event_header, parse_events_list

S = Settings(date="2026-09-21")
MODERN = "8a0a35e7c74bebcc"


def by_id(rows, fight_id):
    return next(r for r in rows if r["fight_id"] == fight_id)


# -- lista de eventos ---------------------------------------------------------


def test_events_list_rows(fixture):
    rows = parse_events_list(fixture("events_list.html"), S)
    assert len(rows) == 27  # 30 <tr> na fixture cortada: 2 de cabeçalho/vazias + 1 evento futuro
    assert all(set(r) == set(EVENTS_COLUMNS) for r in rows)
    first = rows[0]
    assert first == {
        "event_id": MODERN,
        "name": "UFC 331: Van vs. Pantoja 2",
        "date": "2026-09-19",
        "location": "Los Angeles, California, USA",
        "scraped_at": "2026-09-21",
        "source_url": f"http://ufcstats.com/event-details/{MODERN}",
    }
    assert "7e654edcddd71550" not in {r["event_id"] for r in rows}  # futuro (next.png)
    assert len({r["event_id"] for r in rows}) == len(rows)


def test_event_header_matches_list(fixture):
    header = parse_event_header(fixture(f"event_modern_{MODERN}.html"), MODERN, S)
    listed = by_id([{"fight_id": r["event_id"], **r} for r in parse_events_list(fixture("events_list.html"), S)], MODERN)
    for k in ("name", "date", "location"):
        assert header[k] == listed[k]


# -- card ---------------------------------------------------------------------


def test_card_modern_event_counts_and_order(fixture):
    rows = parse_event_card(fixture(f"event_modern_{MODERN}.html"), MODERN, S)
    assert len(rows) == 12
    assert [r["card_position"] for r in rows] == list(range(1, 13))
    assert len({r["fight_id"] for r in rows}) == 12
    assert all(r["event_id"] == MODERN for r in rows)
    assert all(r["scraped_at"] == "2026-09-21" for r in rows)
    assert all(r["source_url"].endswith(r["fight_id"]) for r in rows)


def test_card_title_fight_udec(fixture):
    r = by_id(parse_event_card(fixture(f"event_modern_{MODERN}.html"), MODERN, S), "568ec6af4008355a")
    assert r["fighter_a_id"] == "17e97649403ba428" and r["fighter_b_id"] == "a0f0004aadf10b71"
    assert r["winner_id"] == "17e97649403ba428"  # vencedor vem primeiro no card
    assert r["result_type"] == "win"
    assert (r["weight_class"], r["is_title_fight"], r["is_women"]) == ("Flyweight", True, False)
    assert r["bonuses"] == ["fight_of_the_night"]  # belt não é bônus
    assert (r["method"], r["method_raw"], r["method_detail"]) == ("U-DEC", "U-DEC", None)
    assert r["went_to_decision"] is True
    assert (r["end_round"], r["end_time_seconds"]) == (5, 300)


def test_card_ko_with_bonus_and_sub(fixture):
    rows = parse_event_card(fixture(f"event_modern_{MODERN}.html"), MODERN, S)
    ko = by_id(rows, "fe612d20eec7ef35")
    assert (ko["method"], ko["method_detail"]) == ("KO/TKO", "Elbow")
    assert ko["bonuses"] == ["performance_of_the_night"]
    assert ko["went_to_decision"] is False
    women_sub = by_id(rows, "73304588cef4f88b")
    assert (women_sub["method"], women_sub["method_detail"]) == ("SUB", "Armbar")
    assert women_sub["is_women"] is True and women_sub["weight_class"] == "Flyweight"


def test_card_draw(fixture):
    r = by_id(parse_event_card(fixture("event_with_draw_5c38639f860a5542.html"), "5c38639f860a5542", S), "a997593977ba8cad")
    assert r["result_type"] == "draw"
    assert r["winner_id"] is None
    assert r["method"] == "M-DEC" and r["went_to_decision"] is True
    assert r["fighter_a_id"] == "5987b2458f4b5290" and r["fighter_b_id"] == "0232cabbc30a2372"


def test_card_no_contest(fixture):
    r = by_id(parse_event_card(fixture("event_with_nc_1e75e6c9de99fa76.html"), "1e75e6c9de99fa76", S), "7e8749cbf32ef1f8")
    assert r["result_type"] == "no_contest"
    assert r["winner_id"] is None
    assert r["method"] == "CNC" and r["went_to_decision"] is False
    assert (r["end_round"], r["end_time_seconds"]) == (2, 105)


def test_card_no_unmapped_warnings(fixture, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        for name, eid in [(f"event_modern_{MODERN}.html", MODERN), ("event_with_draw_5c38639f860a5542.html", "5c38639f860a5542")]:
            parse_event_card(fixture(name), eid, S)
    assert not [r for r in caplog.records if "não mapead" in r.message or "desconhecido" in r.message]


def test_card_empty_html():
    assert parse_event_card("<html></html>", "x" * 16, S) == []
