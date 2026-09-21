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

## Fluxo completo

```bash
uv run python -m ufc_scraper crawl    --date 2026-09-21                    # ~13 mil páginas, algumas horas
uv run python -m ufc_scraper parse    --date 2026-09-21                    # 5 tabelas em CSV
uv run python -m ufc_scraper validate --date 2026-09-21                    # critérios de aceite (exit 1 se falhar)
uv run python -m ufc_scraper export   --date 2026-09-21 --format parquet   # ou sqlite
```

Saídas em `data/processed/<date>/`: `events.csv`, `fights.csv`, `fight_stats.csv`,
`round_stats.csv`, `fighters.csv`, `validation_report.md`, `coverage_report.md`,
`*.parquet` / `ufc_stats.sqlite`, `scraper.log`.

## Atualização incremental

Para atualizar uma coleta antiga sem baixar tudo de novo:

```bash
uv run python -m ufc_scraper crawl    --mode incremental --date 2026-11-15 --base-date 2026-09-21
uv run python -m ufc_scraper parse    --date 2026-11-15
uv run python -m ufc_scraper validate --date 2026-11-15
uv run python -m ufc_scraper export   --date 2026-11-15 --format parquet
```

O incremental baixa só a lista de eventos, os **eventos novos** (com suas lutas),
os perfis dos **lutadores envolvidos** nesses eventos (o cartel mudou), as 26 listas
A–Z e perfis de lutadores inéditos nelas. Todo o resto é copiado da coleta-base por
hard link (instantâneo, sem duplicar espaço; a base nunca é alterada). O resultado
é uma pasta `data/raw/<nova-date>/` completa, com `manifest.json` dizendo de onde
veio e o que foi baixado. `--base-date` é opcional: o padrão é a coleta mais
recente em `data/raw/`. Também é retomável com a mesma `--date`.
