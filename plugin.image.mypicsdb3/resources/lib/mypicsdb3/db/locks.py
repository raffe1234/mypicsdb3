from __future__ import annotations

from datetime import datetime, timedelta, timezone
import errno
import hashlib
import os
from typing import Iterable, Optional


SCAN_LOCK_NAME = "catalogue-scan"
MIGRATION_LOCK_NAME = "schema-migration"
METADATA_REFRESH_LOCK_NAME = "metadata-refresh"
LOCATION_ENRICHMENT_LOCK_NAME = "location-enrichment"

# A scan and a schema migration are both catalogue-wide writers. Keeping the
# conflict policy in one module makes future long-running jobs opt into the
# same coordination model instead of inventing incompatible locks.
LOCK_CONFLICTS = {
    SCAN_LOCK_NAME: (MIGRATION_LOCK_NAME, METADATA_REFRESH_LOCK_NAME, LOCATION_ENRICHMENT_LOCK_NAME),
    METADATA_REFRESH_LOCK_NAME: (SCAN_LOCK_NAME, MIGRATION_LOCK_NAME, LOCATION_ENRICHMENT_LOCK_NAME),
    LOCATION_ENRICHMENT_LOCK_NAME: (SCAN_LOCK_NAME, MIGRATION_LOCK_NAME, METADATA_REFRESH_LOCK_NAME),
    MIGRATION_LOCK_NAME: (
        SCAN_LOCK_NAME,
        MIGRATION_LOCK_NAME,
        METADATA_REFRESH_LOCK_NAME,
        LOCATION_ENRICHMENT_LOCK_NAME,
    ),
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



def _owner_process(owner: str):
    parts = str(owner or "").split(":", 2)
    if len(parts) != 3:
        return None
    host, pid_text, _token = parts
    try:
        pid = int(pid_text)
    except (TypeError, ValueError):
        return None
    if not host or pid <= 0:
        return None
    return host, pid


def _process_is_alive(pid: int) -> Optional[bool]:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            query_limited_information = 0x1000
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32
            ]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.SetLastError(0)
            handle = kernel32.OpenProcess(
                query_limited_information, False, int(pid)
            )
            if handle:
                kernel32.CloseHandle(handle)
                return True
            error = int(kernel32.GetLastError())
            if error == 5:  # Access denied still proves that a process exists.
                return True
            if error == 87:  # Invalid parameter is returned for a dead/nonexistent pid.
                return False
            return None
        except Exception:
            return None
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return None
    return True


def recover_stale_sqlite_process_lock(engine, name: str, current_owner: str) -> Optional[str]:
    """Remove a process-owned SQLite lock left by a previous Kodi process.

    SQLite catalogues are profile-local in the supported architecture. Scanner
    owners include hostname and process id. A same-host lock can be recovered
    only when its recorded process is confirmed absent. Shared catalogues use
    MariaDB and deliberately never take this recovery shortcut.
    """
    if engine.backend != "sqlite":
        return None
    current_process = _owner_process(current_owner)
    if current_process is None:
        return None
    current_host, current_pid = current_process
    with engine.transaction(immediate=True) as connection:
        row = engine.fetchone(
            connection,
            "SELECT owner FROM locks WHERE name=?",
            (name,),
        )
        if row is None:
            return None
        stale_owner = str(row.get("owner") or "")
        stale_process = _owner_process(stale_owner)
        if stale_process is None:
            return None
        stale_host, stale_pid = stale_process
        if stale_host != current_host or stale_pid == current_pid:
            return None
        # Only break a local lock when the recorded process is definitely gone.
        # An unknown liveness result is treated as active and left to normal TTL
        # expiry; this avoids turning crash recovery into an unsafe lock override.
        if _process_is_alive(stale_pid) is not False:
            return None
        cursor = engine.execute(
            connection,
            "DELETE FROM locks WHERE name=? AND owner=?",
            (name, stale_owner),
        )
        try:
            removed = int(cursor.rowcount or 0) > 0
        finally:
            cursor.close()
        return stale_owner if removed else None

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
