"""Mapeamento entre entidades, URLs do site e caminhos no cache (spec §2 e §3).

Layout do cache:

    data/raw/<date>/events_list.html
    data/raw/<date>/events/<event_id>.html
    data/raw/<date>/fights/<fight_id>.html
    data/raw/<date>/fighters/<fighter_id>.html
    data/raw/<date>/fighters_list/<letra>.html

`kind` é uma das chaves de `_KINDS`; `key` é o ID hexadecimal (ou a letra,
para `fighters_list`) e é None para `events_list`.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings

# kind -> (subpasta no cache, template do path na URL)
_KINDS: dict[str, tuple[str | None, str]] = {
    "events_list": (None, "/statistics/events/completed?page=all"),
    "event": ("events", "/event-details/{key}"),
    "fight": ("fights", "/fight-details/{key}"),
    "fighter": ("fighters", "/fighter-details/{key}"),
    "fighters_list": ("fighters_list", "/statistics/fighters?char={key}&page=all"),
}

KINDS = tuple(_KINDS)


def _check(kind: str, key: str | None) -> None:
    if kind not in _KINDS:
        raise ValueError(f"kind desconhecido: {kind!r} (esperado um de {KINDS})")
    if kind == "events_list":
        if key is not None:
            raise ValueError("events_list não recebe key")
    elif not key:
        raise ValueError(f"{kind} exige key")


def raw_dir(settings: Settings) -> Path:
    return settings.data_dir / "raw" / settings.date


def processed_dir(settings: Settings) -> Path:
    return settings.data_dir / "processed" / settings.date


def cache_path(settings: Settings, kind: str, key: str | None = None) -> Path:
    _check(kind, key)
    subdir, _ = _KINDS[kind]
    if subdir is None:
        return raw_dir(settings) / "events_list.html"
    return raw_dir(settings) / subdir / f"{key}.html"


def url_for(kind: str, key: str | None = None, base_url: str = "http://ufcstats.com") -> str:
    _check(kind, key)
    _, template = _KINDS[kind]
    return base_url + template.format(key=key)
