"""Extração mínima de links para o crawler (spec §2, fluxo de navegação).

Isto NÃO é o parser: só encontra IDs de entidades no HTML para saber o que
baixar em seguida. Os parsers (Parte 4+) leem os campos de verdade.

IDs do site têm 16 caracteres hexadecimais. Os links aparecem como `href`
(âncoras) e às vezes como `data-link` em `<tr>`; uma regex sobre o HTML
inteiro apanha os dois casos.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

ID_RE = r"([0-9a-f]{16})"
_EVENT_RE = re.compile(r"/event-details/" + ID_RE)
_FIGHT_RE = re.compile(r"/fight-details/" + ID_RE)
_FIGHTER_RE = re.compile(r"/fighter-details/" + ID_RE)
_URL_ID_RE = re.compile(ID_RE + r"/?$")

# Na lista de eventos "completed", a primeira linha é o PRÓXIMO evento (futuro),
# marcado com este ícone. Eventos futuros estão fora do escopo (spec §2).
_NEXT_EVENT_ICON = "next.png"


def extract_id(url: str) -> str:
    """Último segmento hexadecimal da URL: `.../event-details/7e65...` -> `7e65...`."""
    m = _URL_ID_RE.search(url.strip())
    if not m:
        raise ValueError(f"URL sem ID hexadecimal de 16 chars: {url!r}")
    return m.group(1)


def _unique(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def event_ids(events_list_html: str) -> list[str]:
    """IDs dos eventos realizados, na ordem da página (mais recente primeiro).

    Pula a linha do próximo evento (futuro). Usa BeautifulSoup porque precisa
    do contexto da linha para reconhecer o ícone.
    """
    soup = BeautifulSoup(events_list_html, "lxml")
    ids: list[str] = []
    for row in soup.select("tr"):
        if row.find("img", src=lambda s: bool(s) and _NEXT_EVENT_ICON in s):
            continue
        for a in row.select("a[href*='/event-details/']"):
            m = _EVENT_RE.search(a["href"])
            if m:
                ids.append(m.group(1))
    return _unique(ids)


def fight_ids(event_html: str) -> list[str]:
    return _unique(_FIGHT_RE.findall(event_html))


def fighter_ids(html: str) -> list[str]:
    """Serve para página de evento, de luta e lista A–Z."""
    return _unique(_FIGHTER_RE.findall(html))
