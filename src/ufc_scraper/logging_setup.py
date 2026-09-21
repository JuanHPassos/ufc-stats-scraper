"""Logging em console e em arquivo (spec §6: URL, status, tempo e erros de parsing)."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings
from .paths import processed_dir

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(settings: Settings, level: int = logging.INFO) -> Path:
    """Configura o logger raiz com console + arquivo e devolve o caminho do log.

    O arquivo fica em `data/processed/<date>/scraper.log` e é aberto em modo
    append, para que várias execuções (ex.: coleta retomada) fiquem no mesmo log.
    Chamadas repetidas não duplicam handlers.
    """
    log_dir = processed_dir(settings)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "scraper.log"

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(FORMAT)

    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )
    if not has_console:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    has_file = any(
        isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_path.resolve()
        for h in root.handlers
    )
    if not has_file:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return log_path
