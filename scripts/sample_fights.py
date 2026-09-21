#!/usr/bin/env python
"""Sorteia lutas para conferência manual e imprime todas as suas colunas.

    uv run python scripts/sample_fights.py --n 10 --seed 42 [--date 2026-09-21] [--template .specify/manual_check.md]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ufc_scraper.config import Settings
from ufc_scraper.sample import load_processed, manual_check_template, render_fight, sample_fights


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--date", help="pasta da coleta (padrão: hoje)")
    ap.add_argument("--data-dir", dest="data_dir", default="data")
    ap.add_argument("--template", type=Path, help="escreve a tabela vazia de conferência neste arquivo (não sobrescreve se existir)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    settings = Settings(**{k: v for k, v in {"date": args.date, "data_dir": args.data_dir}.items() if v is not None})
    t = load_processed(settings)
    sample = sample_fights(t["fights"], t["events"], n=args.n, seed=args.seed)
    for _, row in sample.iterrows():
        print(render_fight(row, t["fight_stats"], t["round_stats"]))
        print("\n" + "=" * 100 + "\n")
    print(f"{len(sample)} lutas sorteadas (seed={args.seed}): " + ", ".join(sample.era.value_counts().sort_index().map(str).index + "=" + sample.era.value_counts().sort_index().map(str)))

    if args.template:
        if args.template.exists():
            print(f"{args.template} já existe; não sobrescrevo.")
        else:
            args.template.write_text(manual_check_template(sample), encoding="utf-8")
            print(f"template escrito em {args.template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
