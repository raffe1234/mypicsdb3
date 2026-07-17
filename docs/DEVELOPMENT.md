# Development notes

## Design boundaries

- `filesystem.py` isolates Kodi VFS operations.
- `metadata.py` isolates EXIF, XMP and IPTC extraction.
- `db/engine.py` handles SQL parameter syntax and connections.
- `db/catalog.py` contains catalogue writes and read models.
- `scanner.py` never runs from a widget route.
- `views.py` is the Kodi-specific browser and action layer.

## Scanner safety

A source is marked missing only after its root was confirmed available and a
complete, non-cancelled traversal finished. Records are soft-marked missing.
Cleanup removes old missing rows after the configured retention period.

## Schema changes

Increment `SCHEMA_VERSION`, add a deterministic migration, and test upgrades
from every supported schema. Version 0.1.0 contains schema version 1 only.

## MariaDB integration test

```bash
docker compose -f dev/docker-compose.yml up -d
export MYPICSDB3_MYSQL_HOST=127.0.0.1
export MYPICSDB3_MYSQL_PORT=3307
export MYPICSDB3_MYSQL_DATABASE=mypicsdb3
export MYPICSDB3_MYSQL_USERNAME=mypicsdb3
export MYPICSDB3_MYSQL_PASSWORD=mypicsdb3
python3 -m pytest tests/test_mysql_integration.py
```

## Release checklist

```bash
python3 tools/set_version.py 0.2.0
python3 tools/verify.py
python3 -m pytest
python3 tools/build.py
git add -A
git commit -m "Release MyPicsDB 3 0.2.0"
git tag -a v0.2.0 -m "MyPicsDB 3 0.2.0"
git push origin main --follow-tags
```
