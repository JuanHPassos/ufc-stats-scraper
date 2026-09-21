import pytest

from ufc_scraper.links import event_ids, extract_id, fight_ids, fighter_ids


def test_extract_id():
    assert extract_id("http://ufcstats.com/event-details/7e654edcddd71550") == "7e654edcddd71550"
    assert extract_id("http://ufcstats.com/fighter-details/17e97649403ba428/") == "17e97649403ba428"
    with pytest.raises(ValueError):
        extract_id("http://ufcstats.com/statistics/events/completed?page=all")


def test_event_ids_skips_next_event_and_keeps_order(fixture):
    ids = event_ids(fixture("events_list.html"))
    assert "7e654edcddd71550" not in ids  # linha "next" (evento futuro, ícone next.png)
    assert ids[:3] == ["8a0a35e7c74bebcc", "638cfec7ec559d6e", "2144954270be834d"]
    assert len(ids) == len(set(ids))
    assert all(len(i) == 16 for i in ids)


def test_fight_ids_from_event_page(fixture):
    ids = fight_ids(fixture("event_modern_8a0a35e7c74bebcc.html"))
    assert len(ids) == 12
    assert "568ec6af4008355a" in ids and "fe612d20eec7ef35" in ids
    assert len(ids) == len(set(ids))


def test_fighter_ids_from_event_page(fixture):
    ids = fighter_ids(fixture("event_modern_8a0a35e7c74bebcc.html"))
    assert len(ids) == 24  # 12 lutas x 2, ninguém repetido no card
    assert ids[:2] == ["17e97649403ba428", "a0f0004aadf10b71"]  # main event primeiro


def test_fighter_ids_from_fight_page(fixture):
    # href sem aspas na página de luta: <a href=http://.../fighter-details/ID>
    ids = fighter_ids(fixture("fight_udec_title_5r_568ec6af4008355a.html"))
    assert ids == ["17e97649403ba428", "a0f0004aadf10b71"]


def test_fighter_ids_from_az_list_dedupes_name_columns(fixture):
    # cada lutador aparece 3x (nome, sobrenome, apelido) na lista A-Z
    ids = fighter_ids(fixture("fighters_list_x.html"))
    assert len(ids) == 4
    assert ids[0] == "e6dac752a2418a88"


def test_empty_html():
    assert event_ids("<html></html>") == []
    assert fight_ids("") == []
    assert fighter_ids("") == []
