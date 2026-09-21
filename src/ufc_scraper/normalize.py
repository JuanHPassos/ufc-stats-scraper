"""Conversões de texto do site para valores tipados (spec §5).

Todas as funções são puras e seguem as mesmas regras:

- `None`, `""`, `"--"` (e variações com espaços) viram `None`. **Nulo não é zero.**
- Espaços e quebras de linha extras são colapsados; acentos são preservados.
- Valores fora dos conjuntos fixos (`METHOD_MAP`, `WEIGHT_CLASS_MAP`) geram
  `WARNING` no log e são devolvidos limpos, nunca descartados.
- Nenhuma função acessa HTML, rede ou disco.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

NULL_TOKENS = {"", "--", "-", "n/a"}

# -- básicos ------------------------------------------------------------------


def clean_text(s: str | None) -> str | None:
    """Colapsa espaços/quebras e faz strip. Devolve None para vazio ou "--"."""
    if s is None:
        return None
    t = " ".join(str(s).split())
    if t.lower() in NULL_TOKENS:
        return None
    return t


def parse_int(s: str | None) -> int | None:
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"[+-]?\d+", t)
    if not m:
        raise ValueError(f"inteiro inválido: {s!r}")
    return int(t)


def parse_float(s: str | None) -> float | None:
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t)
    if not m:
        raise ValueError(f"decimal inválido: {s!r}")
    return float(t)


def parse_of(s: str | None) -> tuple[int | None, int | None]:
    """"45 of 102" -> (45, 102). "--" -> (None, None)."""
    t = clean_text(s)
    if t is None:
        return (None, None)
    m = re.fullmatch(r"(\d+)\s+of\s+(\d+)", t)
    if not m:
        raise ValueError(f"formato 'X of Y' inválido: {s!r}")
    return (int(m.group(1)), int(m.group(2)))


def parse_percent(s: str | None) -> float | None:
    """"43%" -> 0.43. Só para as estatísticas de carreira do PERFIL do lutador,
    que não têm landed/attempted para recalcular. Nas tabelas de luta os
    percentuais são descartados (spec §5)."""
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", t)
    if not m:
        raise ValueError(f"percentual inválido: {s!r}")
    return round(float(m.group(1)) / 100, 4)


# -- tempo --------------------------------------------------------------------


def parse_mmss(s: str | None) -> int | None:
    """"3:24" -> 204; "15:00" -> 900; "--" -> None."""
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"(\d+):(\d{2})", t)
    if not m:
        raise ValueError(f"tempo m:ss inválido: {s!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


_TIME_FORMAT_RE = re.compile(r"^(\d+)\s*Rnd")
_ROUND_DURATIONS_RE = re.compile(r"\((\d+(?:-\d+)*)\)")


def parse_time_format(s: str | None) -> int | None:
    """"5 Rnd (5-5-5-5-5)" -> 5; "1 Rnd + OT (12-3)" -> 1; "No Time Limit" -> None."""
    t = clean_text(s)
    if t is None:
        return None
    m = _TIME_FORMAT_RE.match(t)
    return int(m.group(1)) if m else None


def round_durations(s: str | None) -> list[int] | None:
    """Minutos de cada round a partir do parêntese: "3 Rnd (10-5-5)" -> [10, 5, 5]."""
    t = clean_text(s)
    if t is None:
        return None
    m = _ROUND_DURATIONS_RE.search(t)
    if not m:
        return None
    return [int(x) for x in m.group(1).split("-")]


_warned_formats: set[str] = set()
DEFAULT_ROUND_MINUTES = 5


def total_fight_seconds(
    end_round: int | None, end_time_seconds: int | None, time_format_raw: str | None
) -> int | None:
    """Duração total: rounds anteriores completos (pelo formato) + tempo no round final.

    Formato desconhecido: assume 5 min por round e loga WARNING uma vez por formato.
    """
    if end_round is None or end_time_seconds is None:
        return None
    durations = round_durations(time_format_raw)
    if durations is None:
        key = clean_text(time_format_raw) or "<vazio>"
        if key not in _warned_formats:
            _warned_formats.add(key)
            log.warning("formato de tempo desconhecido %r: assumindo %d min/round", key, DEFAULT_ROUND_MINUTES)
        durations = []
    previous = 0
    for r in range(end_round - 1):
        previous += durations[r] if r < len(durations) else DEFAULT_ROUND_MINUTES
    return previous * 60 + end_time_seconds


# -- medidas ------------------------------------------------------------------

INCH_CM = 2.54
LB_KG = 0.45359237


def parse_height(s: str | None) -> float | None:
    """"5' 11\"" -> 180.3 cm."""
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"(\d+)'\s*(\d+)\"?", t)
    if not m:
        raise ValueError(f"altura inválida: {s!r}")
    inches = int(m.group(1)) * 12 + int(m.group(2))
    return round(inches * INCH_CM, 1)


def parse_reach(s: str | None) -> float | None:
    """"72\"" -> 182.9 cm."""
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\"?", t)
    if not m:
        raise ValueError(f"envergadura inválida: {s!r}")
    return round(float(m.group(1)) * INCH_CM, 1)


def parse_weight(s: str | None) -> float | None:
    """"155 lbs." -> 70.3 kg."""
    t = clean_text(s)
    if t is None:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*lbs?\.?", t)
    if not m:
        raise ValueError(f"peso inválido: {s!r}")
    return round(float(m.group(1)) * LB_KG, 1)


# -- datas --------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})")


def parse_date(s: str | None) -> str | None:
    """"Mar. 15, 2025" / "March 15, 2025" / "Sep 27, 2000" / "August 01, 2026" -> "YYYY-MM-DD"."""
    t = clean_text(s)
    if t is None:
        return None
    m = _DATE_RE.fullmatch(t)
    if not m:
        raise ValueError(f"data inválida: {s!r}")
    mon = m.group(1).lower()
    month = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
    if month is None:
        raise ValueError(f"mês inválido: {s!r}")
    day, year = int(m.group(2)), int(m.group(3))
    if not 1 <= day <= 31:
        raise ValueError(f"dia inválido: {s!r}")
    return f"{year:04d}-{month:02d}-{day:02d}"


# -- categorias ---------------------------------------------------------------

METHODS = ("KO/TKO", "SUB", "U-DEC", "S-DEC", "M-DEC", "DQ", "OVERTURNED", "CNC", "OTHER")

# Cobre a forma abreviada (card do evento) e a forma por extenso (página da luta).
METHOD_MAP: dict[str, str] = {
    "ko/tko": "KO/TKO",
    "ko": "KO/TKO",
    "tko": "KO/TKO",
    "sub": "SUB",
    "submission": "SUB",
    "u-dec": "U-DEC",
    "decision - unanimous": "U-DEC",
    "s-dec": "S-DEC",
    "decision - split": "S-DEC",
    "m-dec": "M-DEC",
    "decision - majority": "M-DEC",
    "dq": "DQ",
    "disqualification": "DQ",
    "overturned": "OVERTURNED",
    "cnc": "CNC",
    "could not continue": "CNC",
    "other": "OTHER",
}

DECISION_METHODS = frozenset({"U-DEC", "S-DEC", "M-DEC"})


def normalize_method(method: str | None, detail: str | None = None) -> tuple[str | None, str | None]:
    """(method canônico, method_detail). Fora do mapa: WARNING e ("OTHER", texto limpo).

    `detail` é a segunda linha da coluna Method do card (ex.: "Rear Naked Choke");
    vazio vira None.
    """
    m = clean_text(method)
    d = clean_text(detail)
    if m is None:
        return (None, d)
    canonical = METHOD_MAP.get(m.lower())
    if canonical is None and " - " in m:
        # "TKO - Doctor's Stoppage": prefixo conhecido + detalhe
        head, tail = m.split(" - ", 1)
        canonical = METHOD_MAP.get(head.strip().lower())
        if canonical is not None:
            d = d or clean_text(tail)
    if canonical is None:
        log.warning("método não mapeado: %r", m)
        return ("OTHER", d or m)
    return (canonical, d)


def went_to_decision(method: str | None) -> bool | None:
    if method is None:
        return None
    return method in DECISION_METHODS


WEIGHT_CLASSES = (
    "Strawweight", "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
    "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
    "Super Heavyweight", "Catch Weight", "Open Weight",
)
WEIGHT_CLASS_MAP: dict[str, str] = {w.lower(): w for w in WEIGHT_CLASSES}
WEIGHT_CLASS_MAP.update({"catchweight": "Catch Weight", "openweight": "Open Weight"})

# Mais longos primeiro, para "Light Heavyweight" não casar como "Heavyweight".
_WC_ORDERED = sorted(WEIGHT_CLASS_MAP, key=len, reverse=True)


def normalize_weight_class(s: str | None) -> tuple[str | None, bool | None, bool | None]:
    """"UFC Women's Strawweight Title Bout" -> ("Strawweight", True, True).

    Procura a categoria como substring, então tolera qualquer prefixo/sufixo
    ("UFC Interim … Title Bout", "Road to UFC 4 … Tournament Title Bout",
    "Ultimate Fighter 33 … Tournament Title Bout"). `is_title_fight` = contém
    "title" (inclui interinos e títulos de torneio; o texto original fica em
    `weight_class_raw`). Fora do conjunto: WARNING e devolve o texto limpo.
    """
    t = clean_text(s)
    if t is None:
        return (None, None, None)
    low = t.lower()
    is_title = "title" in low
    is_women = "women's" in low or "women’s" in low
    for key in _WC_ORDERED:
        if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", low):
            return (WEIGHT_CLASS_MAP[key], is_title, is_women)
    log.warning("categoria não mapeada: %r", t)
    cleaned = re.sub(r"\s+(title\s+)?bout$", "", low).strip()
    return (" ".join(w.capitalize() for w in cleaned.split()) or t, is_title, is_women)


# -- placares dos juízes ------------------------------------------------------

_JUDGE_RE = re.compile(r"\s*([^\d]+?)\s+(\d+)\s*-\s*(\d+)\s*\.?")
MAX_JUDGE_WORDS = 4


def parse_judges(details: str | None) -> list[dict] | None:
    """"Sal D'Amato 29 - 28. Derek Cleary 29 - 28." ->
    [{"judge": "Sal D'Amato", "score_1": 29, "score_2": 28}, ...].

    `score_1`/`score_2` são a ORDEM LITERAL do site, que não corresponde à ordem
    dos lutadores na página (observado: o vencedor é o 2º número). A atribuição
    a fighter_a/fighter_b é feita no builder de `fights`, pela maioria dos juízes.

    Se o texto não for inteiramente placares, devolve None (o original fica em
    `details_raw`). Um "nome de juiz" com mais de MAX_JUDGE_WORDS palavras
    também invalida: em lutas overturned o site põe uma linha de motivo
    ("Failed Drug Test by X") antes das notas, e se o parser juntar as linhas
    o motivo gruda no primeiro nome. O parser deve passar as linhas de
    `Details:` separadamente.
    """
    t = clean_text(details)
    if t is None:
        return None
    out: list[dict] = []
    pos = 0
    while pos < len(t):
        m = _JUDGE_RE.match(t, pos)
        if not m:
            return None
        judge = m.group(1).strip(" .")
        if len(judge.split()) > MAX_JUDGE_WORDS:
            return None
        out.append({"judge": judge, "score_1": int(m.group(2)), "score_2": int(m.group(3))})
        pos = m.end()
    return out or None


# -- cartel -------------------------------------------------------------------

_RECORD_RE = re.compile(r"(?:Record:\s*)?(\d+)-(\d+)-(\d+)(?:\s*\((\d+)\s*NC\))?")


def parse_record(s: str | None) -> tuple[int | None, int | None, int | None, int | None]:
    """"Record: 9-4-0 (1 NC)" -> (9, 4, 0, 1); "12-3-0" -> (12, 3, 0, None)."""
    t = clean_text(s)
    if t is None:
        return (None, None, None, None)
    m = _RECORD_RE.fullmatch(t)
    if not m:
        raise ValueError(f"cartel inválido: {s!r}")
    nc = int(m.group(4)) if m.group(4) is not None else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), nc)
