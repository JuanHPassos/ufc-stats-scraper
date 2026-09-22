"""Testes das conversões da spec §5. Funções puras; sem HTML, rede ou disco."""

import logging

import pytest

from ufc_scraper import normalize as n

NULLS = [None, "", "--", "  ", " -- ", "\n--\n"]

# -- básicos ------------------------------------------------------------------


@pytest.mark.parametrize("v", NULLS)
def test_nulls_are_none_everywhere(v):
    assert n.clean_text(v) is None
    assert n.parse_int(v) is None
    assert n.parse_float(v) is None
    assert n.parse_of(v) == (None, None)
    assert n.parse_percent(v) is None
    assert n.parse_mmss(v) is None
    assert n.parse_time_format(v) is None
    assert n.round_durations(v) is None
    assert n.parse_height(v) is None
    assert n.parse_reach(v) is None
    assert n.parse_weight(v) is None
    assert n.parse_date(v) is None
    assert n.parse_judges(v) is None
    assert n.parse_record(v) == (None, None, None, None)
    assert n.normalize_method(v) == (None, None)
    assert n.normalize_weight_class(v) == (None, None, None)


def test_clean_text_collapses_whitespace_keeps_accents():
    assert n.clean_text("  José   Aldo\n  Jr. ") == "José Aldo Jr."
    assert n.clean_text("Ciryl\tGane") == "Ciryl Gane"
    assert n.clean_text("0") == "0"  # zero não é nulo


def test_parse_int():
    assert n.parse_int("45") == 45
    assert n.parse_int(" 0 ") == 0
    with pytest.raises(ValueError):
        n.parse_int("45 of 102")


def test_parse_float():
    assert n.parse_float("3.93") == 3.93
    assert n.parse_float("0.0") == 0.0


@pytest.mark.parametrize("s, expected", [("45 of 102", (45, 102)), ("0 of 0", (0, 0)), (" 1  of  3 ", (1, 3))])
def test_parse_of(s, expected):
    assert n.parse_of(s) == expected


def test_parse_of_invalid():
    with pytest.raises(ValueError):
        n.parse_of("45/102")


@pytest.mark.parametrize("s, expected", [("43%", 0.43), ("100%", 1.0), ("0%", 0.0), ("12.5 %", 0.125)])
def test_parse_percent(s, expected):
    assert n.parse_percent(s) == expected


# -- tempo --------------------------------------------------------------------


@pytest.mark.parametrize("s, expected", [("3:24", 204), ("5:00", 300), ("15:00", 900), ("0:07", 7), (" 1:50 ", 110)])
def test_parse_mmss(s, expected):
    assert n.parse_mmss(s) == expected


def test_parse_mmss_invalid():
    with pytest.raises(ValueError):
        n.parse_mmss("3:4")


@pytest.mark.parametrize(
    "s, rounds, durations",
    [
        ("5 Rnd (5-5-5-5-5)", 5, [5, 5, 5, 5, 5]),
        ("3 Rnd (5-5-5)", 3, [5, 5, 5]),
        ("3 Rnd (10-5-5)", 3, [10, 5, 5]),  # visto no site em 2026
        # com overtime o prefixo conta só os rounds regulares; o parêntese dá o máximo real
        ("1 Rnd + OT (12-3)", 2, [12, 3]),
        ("1 Rnd + 2OT (15-3-3)", 3, [15, 3, 3]),
        ("1 Rnd + OT (31-5)", 2, [31, 5]),
        ("1 Rnd (20)", 1, [20]),
        ("No Time Limit", None, None),
    ],
)
def test_parse_time_format_and_round_durations(s, rounds, durations):
    assert n.parse_time_format(s) == rounds
    assert n.round_durations(s) == durations


@pytest.mark.parametrize(
    "end_round, end_time, fmt, expected",
    [
        (3, 300, "3 Rnd (5-5-5)", 900),
        (1, 204, "3 Rnd (5-5-5)", 204),
        (2, 60, "3 Rnd (10-5-5)", 660),  # 10 min do 1º round + 1 min
        (5, 300, "5 Rnd (5-5-5-5-5)", 1500),
        (2, 30, "1 Rnd + OT (12-3)", 750),  # 12 min + 30 s
        (1, 100, "No Time Limit", 100),  # sem rounds anteriores: só o tempo
        (None, 300, "3 Rnd (5-5-5)", None),
        (3, None, "3 Rnd (5-5-5)", None),
    ],
)
def test_total_fight_seconds(end_round, end_time, fmt, expected):
    assert n.total_fight_seconds(end_round, end_time, fmt) == expected


def test_total_fight_seconds_unknown_format_assumes_5min_and_warns_once(caplog):
    n._warned_formats.clear()
    with caplog.at_level(logging.WARNING, logger="ufc_scraper.normalize"):
        assert n.total_fight_seconds(3, 60, "Formato Estranho") == 660
        assert n.total_fight_seconds(2, 0, "Formato Estranho") == 300
    assert sum("formato de tempo desconhecido" in r.message for r in caplog.records) == 1


# -- medidas ------------------------------------------------------------------


@pytest.mark.parametrize("s, expected", [("5' 11\"", 180.3), ("5' 5\"", 165.1), ("6' 0\"", 182.9), ("5'11\"", 180.3)])
def test_parse_height(s, expected):
    assert n.parse_height(s) == expected


@pytest.mark.parametrize("s, expected", [('72"', 182.9), ('65"', 165.1), ("70", 177.8), ('72.5"', 184.2)])
def test_parse_reach(s, expected):
    assert n.parse_reach(s) == expected


@pytest.mark.parametrize("s, expected", [("155 lbs.", 70.3), ("125 lbs.", 56.7), ("265 lbs", 120.2), ("145 lbs.", 65.8)])
def test_parse_weight(s, expected):
    assert n.parse_weight(s) == expected


def test_measure_invalid():
    with pytest.raises(ValueError):
        n.parse_height("180 cm")
    with pytest.raises(ValueError):
        n.parse_weight("70 kg")


# -- datas --------------------------------------------------------------------


@pytest.mark.parametrize(
    "s, expected",
    [
        ("Mar. 15, 2025", "2025-03-15"),
        ("March 15, 2025", "2025-03-15"),
        ("Mar 15, 2025", "2025-03-15"),
        ("Sep 27, 2000", "2000-09-27"),
        ("Sept. 5, 1999", "1999-09-05"),
        ("August 01, 2026", "2026-08-01"),
        ("  November  12,  1993 ", "1993-11-12"),
    ],
)
def test_parse_date(s, expected):
    assert n.parse_date(s) == expected


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        n.parse_date("15/03/2025")
    with pytest.raises(ValueError):
        n.parse_date("Foo 15, 2025")


# -- método -------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, detail, expected",
    [
        ("U-DEC", "", ("U-DEC", None)),
        ("S-DEC", None, ("S-DEC", None)),
        ("M-DEC", "", ("M-DEC", None)),
        ("KO/TKO", "Punches", ("KO/TKO", "Punches")),
        ("SUB", "Rear Naked Choke", ("SUB", "Rear Naked Choke")),
        ("CNC", "", ("CNC", None)),
        ("DQ", "Illegal Knee", ("DQ", "Illegal Knee")),
        ("Overturned", "", ("OVERTURNED", None)),
        # forma por extenso (página da luta)
        ("Decision - Unanimous", None, ("U-DEC", None)),
        ("Decision - Split", None, ("S-DEC", None)),
        ("Decision - Majority", None, ("M-DEC", None)),
        ("Submission", None, ("SUB", None)),
        ("Could Not Continue", None, ("CNC", None)),
        ("  ko/tko  ", " Punch ", ("KO/TKO", "Punch")),
        ("TKO - Doctor's Stoppage", None, ("KO/TKO", "Doctor's Stoppage")),  # visto no site
        ("KO - Punch", "", ("KO/TKO", "Punch")),
        ("TKO - Doctor's Stoppage", "Cut", ("KO/TKO", "Cut")),  # detalhe explícito prevalece
    ],
)
def test_normalize_method(method, detail, expected):
    assert n.normalize_method(method, detail) == expected


def test_normalize_method_unmapped_warns_and_keeps_text(caplog):
    with caplog.at_level(logging.WARNING, logger="ufc_scraper.normalize"):
        assert n.normalize_method("Technical Decision", "") == ("OTHER", "Technical Decision")
        assert n.normalize_method("Weird", "Detail") == ("OTHER", "Detail")
    assert any("método não mapeado" in r.message for r in caplog.records)


def test_method_map_values_are_canonical():
    assert set(n.METHOD_MAP.values()) <= set(n.METHODS)


@pytest.mark.parametrize("m, expected", [("U-DEC", True), ("S-DEC", True), ("M-DEC", True), ("KO/TKO", False), ("SUB", False), ("CNC", False), (None, None)])
def test_went_to_decision(m, expected):
    assert n.went_to_decision(m) is expected


# -- categoria ----------------------------------------------------------------


@pytest.mark.parametrize(
    "s, expected",
    [
        ("Lightweight Bout", ("Lightweight", False, False)),
        ("Lightweight", ("Lightweight", False, False)),
        ("Light Heavyweight Bout", ("Light Heavyweight", False, False)),
        ("Women's Strawweight Bout", ("Strawweight", False, True)),
        ("Women's Bantamweight", ("Bantamweight", False, True)),
        ("UFC Flyweight Title Bout", ("Flyweight", True, False)),
        ("UFC Women's Strawweight Title Bout", ("Strawweight", True, True)),
        ("UFC Interim Heavyweight Title Bout", ("Heavyweight", True, False)),
        ("Catch Weight Bout", ("Catch Weight", False, False)),
        ("Open Weight Bout", ("Open Weight", False, False)),
        ("Super Heavyweight Bout", ("Super Heavyweight", False, False)),
        ("Road to UFC 4 Lightweight Tournament Title Bout", ("Lightweight", True, False)),
        ("Ultimate Fighter 33 Flyweight Tournament Title Bout", ("Flyweight", True, False)),
        ("UFC Women's Featherweight Title Bout", ("Featherweight", True, True)),
        ("Heavyweight", ("Heavyweight", False, False)),
    ],
)
def test_normalize_weight_class(s, expected):
    assert n.normalize_weight_class(s) == expected


def test_normalize_weight_class_unmapped_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="ufc_scraper.normalize"):
        wc, is_title, is_women = n.normalize_weight_class("UFC Tournament Title Bout")
    assert (is_title, is_women) == (True, False)
    assert wc and "bout" not in wc.lower()  # texto limpo, sem o sufixo
    assert any("categoria não mapeada" in r.message for r in caplog.records)


# -- juízes -------------------------------------------------------------------


def test_parse_judges_three_scores():
    s = "Sal D'Amato 29 - 28. Derek Cleary 29 - 28. Chris Lee 30 - 27."
    assert n.parse_judges(s) == [
        {"judge": "Sal D'Amato", "score_1": 29, "score_2": 28},
        {"judge": "Derek Cleary", "score_1": 29, "score_2": 28},
        {"judge": "Chris Lee", "score_1": 30, "score_2": 27},
    ]


def test_parse_judges_real_site_text_and_5_rounds():
    s = "Sal D'amato 46 - 49. Derek Cleary 47 - 48. Ron McCarthy 45 - 50."
    out = n.parse_judges(s)
    assert [j["judge"] for j in out] == ["Sal D'amato", "Derek Cleary", "Ron McCarthy"]
    assert (out[0]["score_1"], out[0]["score_2"]) == (46, 49)


def test_parse_judges_without_trailing_dot_and_extra_spaces():
    assert n.parse_judges("  Eric Colon  28-29.  Mike Bell 27 - 29 ") == [
        {"judge": "Eric Colon", "score_1": 28, "score_2": 29},
        {"judge": "Mike Bell", "score_1": 27, "score_2": 29},
    ]


@pytest.mark.parametrize("s", ["Punch to Head At Distance", "Rear Naked Choke", "Sal D'amato 28 - 29. Rear Naked Choke"])
def test_parse_judges_non_scores_return_none(s):
    assert n.parse_judges(s) is None


# -- cartel -------------------------------------------------------------------


@pytest.mark.parametrize(
    "s, expected",
    [
        ("Record: 12-3-0", (12, 3, 0, 0)),  # sem sufixo = 0 NC, não nulo
        ("Record: 9-4-0 (1 NC)", (9, 4, 0, 1)),
        ("21-0-0", (21, 0, 0, 0)),
        ("  Record:  30-5-1  (2 NC) ", (30, 5, 1, 2)),
    ],
)
def test_parse_record(s, expected):
    assert n.parse_record(s) == expected


def test_parse_record_invalid():
    with pytest.raises(ValueError):
        n.parse_record("12-3")


def test_parse_judges_overturned_reason_glued_to_first_name_is_rejected():
    # Caso real (luta 7ffdaa44fc8d111b): linha de motivo + placares. Se as linhas forem
    # juntadas, o motivo gruda no 1º nome e o resultado seria lixo -> None.
    glued = "Failed Drug Test by Idiris Ryan Thompson 29 - 28. Sal D'amato 30 - 27. Junichiro Kamijo 30 - 27."
    assert n.parse_judges(glued) is None
    # Linhas separadas (como o parser da Parte 4 deve passar) funcionam.
    scores_only = "Ryan Thompson 29 - 28.\nSal D'amato 30 - 27.\nJunichiro Kamijo 30 - 27."
    assert [j["judge"] for j in n.parse_judges(scores_only)] == ["Ryan Thompson", "Sal D'amato", "Junichiro Kamijo"]
