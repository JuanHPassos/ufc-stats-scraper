"""CLI do scraper.

    python -m ufc_scraper crawl    --date YYYY-MM-DD [--limit N] [--mode full|incremental]
    python -m ufc_scraper parse    --date YYYY-MM-DD [--table events|fights|fight_stats|round_stats|fighters]
    python -m ufc_scraper validate --date YYYY-MM-DD
    python -m ufc_scraper export   --date YYYY-MM-DD --format csv|parquet|sqlite

Cada subcomando é ligado à sua implementação na parte correspondente do plano
(.specify/plan.md). Enquanto não implementado, sai com código 2.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings, settings_from_args
from .http import ChallengeRequired
from .logging_setup import setup_logging

log = logging.getLogger("ufc_scraper")

TABLES = ("events", "fights", "fight_stats", "round_stats", "fighters")
FORMATS = ("csv", "parquet", "sqlite")
EXIT_NOT_IMPLEMENTED = 2
EXIT_CHALLENGE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufc_scraper",
        description="Scraper do UFC Stats: coleta HTML bruto e gera tabelas relacionais.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", help="Pasta da coleta (YYYY-MM-DD). Padrão: hoje.")
    common.add_argument("--data-dir", dest="data_dir", help="Raiz dos dados. Padrão: data/")

    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", parents=[common], help="Baixa o HTML bruto para data/raw/<date>/")
    crawl.add_argument("--limit", type=int, help="Limita o número de eventos (amostra para testes)")
    crawl.add_argument("--mode", choices=("full", "incremental"), help="Padrão: full")
    crawl.add_argument("--delay-min", dest="delay_min", type=float, help="Intervalo mínimo entre requisições (s)")
    crawl.add_argument("--delay-max", dest="delay_max", type=float, help="Intervalo máximo entre requisições (s)")

    parse = sub.add_parser("parse", parents=[common], help="Gera as tabelas a partir do HTML salvo")
    parse.add_argument("--table", choices=TABLES, help="Só esta tabela. Padrão: todas as implementadas")

    sub.add_parser("validate", parents=[common], help="Roda os critérios de aceite (spec §7)")

    export = sub.add_parser("export", parents=[common], help="Exporta as tabelas")
    export.add_argument("--format", choices=FORMATS, default="parquet")

    return parser


def _not_implemented(command: str) -> int:
    log.error("comando %r ainda não implementado (ver .specify/plan.md)", command)
    return EXIT_NOT_IMPLEMENTED


def cmd_crawl(args: argparse.Namespace, settings: Settings) -> int:
    from .crawl import run_crawl

    if settings.mode == "incremental":
        return _not_implemented("crawl --mode incremental")  # Parte 9
    try:
        report = run_crawl(settings, limit=args.limit)
    except ChallengeRequired as exc:
        log.critical("coleta abortada: desafio anti-bot não passou (%s)", exc)
        return EXIT_CHALLENGE
    return 1 if report.failed else 0


def run(args: argparse.Namespace, settings: Settings) -> int:
    """Despacha o subcomando. Cada parte do plano substitui o stub correspondente."""
    if args.command == "crawl":
        return cmd_crawl(args, settings)
    return _not_implemented(args.command)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = settings_from_args(args)
    except ValueError as exc:
        print(f"erro de configuração: {exc}", file=sys.stderr)
        return 1
    setup_logging(settings)
    log.info("comando=%s date=%s data_dir=%s", args.command, settings.date, settings.data_dir)
    return run(args, settings)


if __name__ == "__main__":
    sys.exit(main())
