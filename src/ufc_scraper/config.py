"""Configuração do scraper (spec §6).

Todos os parâmetros de execução vivem em `Settings`. A CLI constrói a
instância via `settings_from_args`; o código nunca lê `sys.argv` diretamente.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BASE_URL = "http://ufcstats.com"

# Contato do grupo, exigido pela spec §6 (User-Agent identificável).
CONTACT_EMAIL = "juan.passos01@usp.br"

Mode = str  # "full" | "incremental"


def today_iso() -> str:
    return date.today().isoformat()


@dataclass
class Settings:
    base_url: str = BASE_URL
    data_dir: Path = Path("data")
    # Pasta da coleta (YYYY-MM-DD). Retomar uma coleta exige passar a mesma data.
    date: str = field(default_factory=today_iso)
    delay_min: float = 1.0
    delay_max: float = 2.0
    timeout: int = 30
    max_retries: int = 3
    backoff: tuple[int, ...] = (5, 15, 45)
    user_agent: str = f"ufc-stats-scraper/0.1 (trabalho academico; contato: {CONTACT_EMAIL})"
    mode: Mode = "full"

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.mode not in ("full", "incremental"):
            raise ValueError(f"mode inválido: {self.mode!r}")
        if self.delay_min > self.delay_max:
            raise ValueError("delay_min não pode ser maior que delay_max")
        # Valida o formato da data cedo, para não criar pasta com nome errado.
        date.fromisoformat(self.date)


def settings_from_args(args: argparse.Namespace) -> Settings:
    """Constrói Settings a partir do Namespace da CLI.

    Só sobrescreve os campos presentes (não-None) no Namespace, para que
    subcomandos com flags diferentes compartilhem a mesma função.
    """
    kwargs: dict = {}
    for name in ("data_dir", "date", "delay_min", "delay_max", "mode"):
        value = getattr(args, name, None)
        if value is not None:
            kwargs[name] = value
    return Settings(**kwargs)
