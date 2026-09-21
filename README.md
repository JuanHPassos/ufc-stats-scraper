# ufc-stats-scraper

Scraper do [UFC Stats](http://ufcstats.com/statistics/events/completed) para um
trabalho de ciência de dados em grupo. Baixa o HTML bruto de todos os eventos,
lutas e lutadores, e gera cinco tabelas relacionais limpas (`events`, `fights`,
`fight_stats`, `round_stats`, `fighters`). O scraper não faz análise.

- Especificação: [.specify/spec.md](.specify/spec.md)
- Plano de execução (partes sequenciais, status e critérios): [.specify/plan.md](.specify/plan.md)

## Instalação

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest -q
```

## Uso

```bash
uv run python -m ufc_scraper --help
uv run python -m ufc_scraper crawl    --date 2026-09-21 [--limit 3] [--mode full|incremental]
uv run python -m ufc_scraper parse    --date 2026-09-21 [--table events]
uv run python -m ufc_scraper validate --date 2026-09-21
uv run python -m ufc_scraper export   --date 2026-09-21 --format parquet
```

A pasta de coleta é `data/raw/<date>/` e a saída processada fica em
`data/processed/<date>/` (ambas ignoradas pelo git). Para retomar uma coleta
interrompida, rode o mesmo comando **com a mesma `--date`**.
