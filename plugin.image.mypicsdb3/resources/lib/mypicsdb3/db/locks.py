from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Iterable, Optional


SCAN_LOCK_NAME = "catalogue-scan"
MIGRATION_LOCK_NAME = "schema-migration"

# A scan and a schema migration are both catalogue-wide writers. Keeping the
# conflict policy in one module makes future long-running jobs opt into the
# same coordination model instead of inventing incompatible locks.
LOCK_CONFLICTS = {
    SCAN_LOCK_NAME: (MIGRATION_LOCK_NAME,),
    MIGRATION_LOCK_NAME: (SCAN_LOCK_NAME, MIGRATION_LOCK_NAME),
}


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def acquire_lock(
    engine,
    name: str,
    owner: str,
    ttl_seconds: int = 1800,
    blocked_by: Optional[Iterable[str]] = None,
) -> bool:
    now_dt = datetime.now(timezone.utc)
    now = _timestamp(now_dt)
    expires = _timestamp(now_dt + timedelta(seconds=ttl_seconds))
    blockers = set(blocked_by if blocked_by is not None else LOCK_CONFLICTS.get(name, ()))
    blockers.add(name)

    coordinator = None
    try:
        if engine.backend == "mysql":
            # MySQL transactions do not serialize inserts of different lock
            # names. A short named lock makes the cross-lock conflict check
            # atomic for all MyPicsDB 3 clients sharing this database.
            coordinator = engine.connect()
            database = str(engine.settings.mysql_database).encode("utf-8")
            coordinator_name = "mypicsdb3-lock-" + hashlib.sha256(database).hexdigest()[:32]
            row = engine.fetchone(
                coordinator,
                "SELECT GET_LOCK(?, 5) AS acquired",
                (coordinator_name,),
            )
            if not row or int(row.get("acquired") or 0) != 1:
                return False

        with engine.transaction(immediate=True) as connection:
            engine.execute(connection, "DELETE FROM locks WHERE expires_at<=?", (now,)).close()
            placeholders = ",".join("?" for _ in blockers)
            existing = engine.fetchone(
                connection,
                "SELECT name, owner FROM locks WHERE name IN (%s) LIMIT 1" % placeholders,
                tuple(sorted(blockers)),
            )
            if existing is not None:
                return False
            engine.execute(
                connection,
                "INSERT INTO locks (name, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                (name, owner, now, expires),
            ).close()
        return True
    except engine.integrity_errors:
        return False
    finally:
        if coordinator is not None:
            try:
                engine.fetchone(coordinator, "SELECT RELEASE_LOCK(?) AS released", (coordinator_name,))
            finally:
                coordinator.close()


def refresh_lock(engine, name: str, owner: str, ttl_seconds: int = 1800, connection=None) -> bool:
    now_dt = datetime.now(timezone.utc)
    now = _timestamp(now_dt)
    expires = _timestamp(now_dt + timedelta(seconds=ttl_seconds))

    def update(active_connection) -> bool:
        cursor = engine.execute(
            active_connection,
            "UPDATE locks SET expires_at=? WHERE name=? AND owner=? AND expires_at>?",
            (expires, name, owner, now),
        )
        try:
            updated = int(cursor.rowcount or 0) > 0
        finally:
            cursor.close()
        if updated:
            return True
        current = engine.fetchone(
            active_connection,
            "SELECT owner, expires_at FROM locks WHERE name=?",
            (name,),
        )
        return bool(current and current.get("owner") == owner and str(current.get("expires_at") or "") > now)

    if connection is not None:
        return update(connection)
    with engine.transaction(immediate=True) as active_connection:
        return update(active_connection)


def release_lock(engine, name: str, owner: str) -> None:
    with engine.transaction() as connection:
        engine.execute(connection, "DELETE FROM locks WHERE name=? AND owner=?", (name, owner)).close()
