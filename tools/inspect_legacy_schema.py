#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from schema_inspector import inspect_mysql, inspect_sqlite


SIGNATURE_GROUPS = {
    "mypicsdb-style file catalogue": {"files", "folders"},
    "root/source catalogue": {"roots", "sources"},
    "tag catalogue": {"tags", "tagtypes", "tagvalues"},
    "collection catalogue": {"collections"},
    "saved filter catalogue": {"filters"},
    "named period catalogue": {"periods"},
    "translation catalogue": {"translations"},
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a legacy MyPicsDB database in read-only mode"
    )
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

    table_names = {str(table["name"]).casefold() for table in report["tables"]}
    signatures = []
    for label, candidates in SIGNATURE_GROUPS.items():
        matched = sorted(name for name in candidates if name.casefold() in table_names)
        if matched:
            signatures.append({"signature": label, "matched_tables": matched})
    report["legacy_analysis"] = {
        "identified_signatures": signatures,
        "unknown_tables": sorted(
            table_names
            - {name.casefold() for candidates in SIGNATURE_GROUPS.values() for name in candidates}
        ),
        "warning": (
            "This report only inventories the schema. Do not implement an importer "
            "until each legacy version has a verified adapter and fixture database."
        ),
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
