#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "plugin.image.mypicsdb3" / "resources" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from mypicsdb3 import SCHEMA_VERSION, VERSION  # noqa: E402
from schema_inspector import inspect_mysql, inspect_sqlite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a MyPicsDB 3 database without changing it")
    parser.add_argument("database", help="SQLite path or MySQL/MariaDB database name")
    parser.add_argument("--backend", choices=("sqlite", "mysql"), default="sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--username", default="kodi")
    parser.add_argument("--password", default="")
    parser.add_argument("--skip-row-counts", action="store_true")
    parser.add_argument("--output", help="Write JSON to this file instead of stdout")
    args = parser.parse_args()

    if args.backend == "mysql":
        report = inspect_mysql(
            args.host,
            args.port,
            args.database,
            args.username,
            args.password,
            include_row_counts=not args.skip_row_counts,
        )
    else:
        report = inspect_sqlite(args.database, include_row_counts=not args.skip_row_counts)
    report["inspector"] = {
        "addon_version": VERSION,
        "supported_schema_version": SCHEMA_VERSION,
        "schema_is_supported": str(report.get("schema_version")) == str(SCHEMA_VERSION),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
