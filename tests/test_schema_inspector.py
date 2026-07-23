from __future__ import annotations

import sys
from pathlib import Path

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from schema_inspector import inspect_sqlite  # noqa: E402


def test_sqlite_schema_inspector_reports_version_history_and_fingerprint(tmp_path: Path) -> None:
    settings = Settings(profile_path=str(tmp_path), database_backend="sqlite")
    Catalog(DatabaseEngine(settings)).initialize()

    report = inspect_sqlite(settings.sqlite_path)

    assert report["backend"] == "sqlite"
    assert report["schema_version"] == "2"
    assert [row["version"] for row in report["migration_history"]] == [1, 2]
    assert len(report["schema_fingerprint"]) == 64
    assert "schema_migrations" in {table["name"] for table in report["tables"]}
