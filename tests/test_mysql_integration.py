from __future__ import annotations

import os

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine


@pytest.mark.skipif(not os.environ.get("MYPICSDB3_TEST_MYSQL"), reason="MySQL integration test is opt-in")
def test_mysql_or_mariadb_schema_and_source_roundtrip(tmp_path) -> None:
    settings = Settings(
        profile_path=str(tmp_path),
        database_backend="mysql",
        mysql_host=os.environ.get("MYPICSDB3_MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.environ.get("MYPICSDB3_MYSQL_PORT", "3306")),
        mysql_database=os.environ.get("MYPICSDB3_MYSQL_DATABASE", "mypicsdb3_test"),
        mysql_username=os.environ.get("MYPICSDB3_MYSQL_USERNAME", "mypicsdb3"),
        mysql_password=os.environ.get("MYPICSDB3_MYSQL_PASSWORD", "mypicsdb3"),
        mysql_auto_create=True,
    )
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    sources = catalog.sync_sources([{"label": "Test", "uri": "/tmp/photos"}])
    assert sources[0].label == "Test"
    catalog.test_connection()
