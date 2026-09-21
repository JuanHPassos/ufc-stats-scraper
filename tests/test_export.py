import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ufc_scraper.config import Settings
from ufc_scraper.export import SCHEMA, export, load_typed
from ufc_scraper.parse import BUILDERS
from ufc_scraper.paths import cache_path

FX = Path(__file__).parent / "fixtures"


@pytest.fixture
def processed(tmp_path):
    s = Settings(data_dir=tmp_path, date="2026-09-21")
    for kind, key, name in [
        ("events_list", None, "events_list.html"),
        ("event", "8a0a35e7c74bebcc", "event_modern_8a0a35e7c74bebcc.html"),
        ("fight", "568ec6af4008355a", "fight_udec_title_5r_568ec6af4008355a.html"),
        ("fighter", "17e97649403ba428", "fighter_17e97649403ba428.html"),
    ]:
        p = cache_path(s, kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FX / name, p)
    for build in BUILDERS.values():
        build(s)
    return s


def test_schema_covers_every_csv_column(processed):
    for name in SCHEMA:
        df = load_typed(processed, name)
        assert list(df.columns) == list(SCHEMA[name])


def test_typed_dtypes(processed):
    f = load_typed(processed, "fights")
    assert str(f.card_position.dtype) == "Int64" and str(f.is_title_fight.dtype) == "boolean"
    assert str(f.fight_id.dtype) == "string"
    assert f.scraped_at.iloc[0].isoformat() == "2026-09-21"
    fs = load_typed(processed, "fight_stats")
    assert str(fs.kd.dtype) == "Int64"
    ft = load_typed(processed, "fighters")
    assert str(ft.height_cm.dtype) == "Float64" and ft.dob.iloc[0].isoformat() == "2001-10-10"


def test_export_parquet(processed):
    paths = export(processed, "parquet")
    assert len(paths) == 5 and all(p.exists() for p in paths)
    f = pd.read_parquet(processed.data_dir / "processed" / "2026-09-21" / "fights.parquet")
    assert len(f) == 12 and str(f.end_round.dtype) == "Int64"
    assert f.set_index("fight_id").loc["568ec6af4008355a", "is_title_fight"] == True  # noqa: E712
    missing_page = f[f.fight_id != "568ec6af4008355a"]
    assert missing_page.referee.isna().all()  # nulo, não string vazia


def test_export_sqlite(processed):
    (path,) = export(processed, "sqlite")
    con = sqlite3.connect(path)
    try:
        assert con.execute("select count(*) from fights").fetchone()[0] == 12
        pk = [r[1] for r in con.execute("pragma table_info(round_stats)") if r[5] > 0]
        assert pk == ["fight_id", "fighter_id", "round"]
        row = con.execute("select is_title_fight, end_round, referee from fights where fight_id='568ec6af4008355a'").fetchone()
        assert row == (1, 5, "Herb Dean")
        assert con.execute("select referee from fights where fight_id != '568ec6af4008355a' limit 1").fetchone() == (None,)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("insert into events (event_id) values ('8a0a35e7c74bebcc')")
    finally:
        con.close()
    (path2,) = export(processed, "sqlite")  # reexportar sobrescreve, sem duplicar
    con = sqlite3.connect(path2)
    assert con.execute("select count(*) from events").fetchone()[0] == 27
    con.close()


def test_export_csv_and_unknown(processed):
    assert len(export(processed, "csv")) == 5
    with pytest.raises(ValueError):
        export(processed, "xml")


def test_cli_validate_and_export(processed):
    import ufc_scraper.__main__ as cli

    base = ["--date", "2026-09-21", "--data-dir", str(processed.data_dir)]
    assert cli.main(["validate", *base]) == 1  # amostra incompleta: integridade falha
    assert cli.main(["export", *base, "--format", "parquet"]) == 0
    assert cli.main(["export", *base, "--format", "sqlite"]) == 0
