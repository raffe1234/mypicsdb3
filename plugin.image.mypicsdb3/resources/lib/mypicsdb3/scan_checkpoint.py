from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .config import Settings
from .models import ScanStats, Source
from .source_scan_policy import (
    SourceScanPolicy,
    source_scan_policy_from_settings,
    source_scan_policy_signature_payload,
)
from .utils import normalize_uri, sha256_text


CHECKPOINT_VERSION = 1
CHECKPOINT_FILENAME = "scan-checkpoint-v1.json"
CHECKPOINT_MAX_AGE_SECONDS = 24 * 60 * 60

_STATS_FIELDS = (
    "sources_total",
    "sources_scanned",
    "sources_unavailable",
    "folders_seen",
    "pictures_seen",
    "pictures_added",
    "pictures_updated",
    "pictures_unchanged",
    "missing_marked",
    "errors",
)


def _stats_to_dict(stats: ScanStats) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        name: max(0, int(getattr(stats, name, 0) or 0)) for name in _STATS_FIELDS
    }
    value.update(
        {
            "started_at": stats.started_at,
            "error_messages": [str(message) for message in stats.error_messages[-20:]],
        }
    )
    return value


def _stats_from_dict(value: Any, default_started_at: Optional[str] = None) -> ScanStats:
    data = value if isinstance(value, dict) else {}
    stats = ScanStats(started_at=str(data.get("started_at") or default_started_at or "") or None)
    for name in _STATS_FIELDS:
        try:
            setattr(stats, name, max(0, int(data.get(name, 0) or 0)))
        except (TypeError, ValueError):
            setattr(stats, name, 0)
    messages = data.get("error_messages")
    if isinstance(messages, list):
        stats.error_messages = [str(message) for message in messages[-20:]]
    return stats


class ScanCheckpointStore:
    """Persist one resumable scan plan in the local Kodi add-on profile.

    The catalogue lock guarantees that only one scanner owns this file at a
    time. The checkpoint is intentionally local even when the catalogue uses
    MySQL/MariaDB: a resumed traversal must continue on the Kodi device that
    owns the filesystem/VFS session and its source paths.
    """

    def __init__(
        self,
        settings: Settings,
        logger=None,
        time_provider=time.time,
        max_age_seconds: int = CHECKPOINT_MAX_AGE_SECONDS,
    ):
        self.settings = settings
        self.logger = logger
        self.time_provider = time_provider
        self.max_age_seconds = max(1, int(max_age_seconds))
        self.path = settings.profile_path.rstrip("/\\") + "/" + CHECKPOINT_FILENAME
        self._state: Dict[str, Any] = {}
        self._signature = ""
        self._source_ids: List[int] = []
        self.resumed = False

    def _log(self, level: str, message: str, *args) -> None:
        if self.logger is None:
            return
        method = getattr(self.logger, level, None)
        if callable(method):
            method(message, *args)

    def _database_identity(self) -> Dict[str, Any]:
        if self.settings.database_backend == "mysql":
            return {
                "backend": "mysql",
                "host": self.settings.mysql_host,
                "port": int(self.settings.mysql_port),
                "database": self.settings.mysql_database,
                "username": self.settings.mysql_username,
            }
        return {
            "backend": "sqlite",
            "path": os.path.abspath(self.settings.sqlite_path),
        }

    def _scan_signature(
        self,
        sources: Sequence[Source],
        source_policies: Optional[Mapping[int, SourceScanPolicy]] = None,
        metadata_index_hash: str = "",
    ) -> str:
        default_policy = source_scan_policy_from_settings(self.settings)
        policies = source_policies or {}
        payload = {
            "version": CHECKPOINT_VERSION,
            "database": self._database_identity(),
            "sources": [
                {
                    "id": int(source.id),
                    "uri": normalize_uri(source.uri, directory=True),
                    "policy": source_scan_policy_signature_payload(
                        policies.get(int(source.id), default_policy)
                    ),
                }
                for source in sources
            ],
            "metadata_index_hash": str(metadata_index_hash or ""),
            "settings": {
                "read_xmp": bool(self.settings.read_xmp),
                "read_iptc": bool(self.settings.read_iptc),
                "store_gps": bool(self.settings.store_gps),
                "metadata_prefix_mb": int(self.settings.metadata_prefix_mb),
                "deep_metadata_max_mb": int(self.settings.deep_metadata_max_mb),
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256_text(encoded)

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError:
            return {}
        except Exception as exc:
            self._log("warning", "Could not read scan checkpoint; starting again: %s", exc)
            self.clear()
            return {}
        return value if isinstance(value, dict) else {}

    def _write(self) -> None:
        if not self._state:
            return
        self._state["updated_at"] = float(self.time_provider())
        parent = os.path.dirname(self.path)
        temporary = self.path + ".tmp"
        try:
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    self._state,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception as exc:
            self._log("warning", "Could not save scan checkpoint: %s", exc)
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except Exception:
                pass

    def clear(self) -> None:
        self._state = {}
        self.resumed = False
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception as exc:
            self._log("warning", "Could not remove scan checkpoint: %s", exc)

    @staticmethod
    def _valid_pending(value: Any) -> bool:
        if not isinstance(value, list):
            return False
        return all(
            isinstance(item, list)
            and len(item) == 3
            and all(isinstance(part, str) for part in item)
            for item in value
        )

    def _is_valid(self, state: Dict[str, Any], sources: Sequence[Source]) -> bool:
        if int(state.get("version", 0) or 0) != CHECKPOINT_VERSION:
            return False
        if str(state.get("signature") or "") != self._signature:
            return False
        if state.get("source_ids") != self._source_ids:
            return False
        try:
            age = float(self.time_provider()) - float(state.get("updated_at", 0) or 0)
        except (TypeError, ValueError):
            return False
        if age < -300 or age > self.max_age_seconds:
            return False

        completed = state.get("completed_source_ids")
        if not isinstance(completed, list):
            return False
        try:
            completed_ids = [int(value) for value in completed]
        except (TypeError, ValueError):
            return False
        if len(completed_ids) != len(set(completed_ids)):
            return False
        if any(source_id not in self._source_ids for source_id in completed_ids):
            return False

        current = state.get("current_source")
        if current is None:
            return True
        if not isinstance(current, dict):
            return False
        try:
            current_id = int(current.get("source_id"))
        except (TypeError, ValueError):
            return False
        remaining_ids = [
            source_id for source_id in self._source_ids if source_id not in completed_ids
        ]
        if not remaining_ids or current_id != remaining_ids[0]:
            return False
        source_by_id = {int(source.id): source for source in sources}
        source = source_by_id.get(current_id)
        if source is None:
            return False
        if str(current.get("source_uri") or "") != normalize_uri(
            source.uri, directory=True
        ):
            return False
        if not str(current.get("scan_started_at") or ""):
            return False
        if not isinstance(current.get("traversal_complete"), bool):
            return False
        return self._valid_pending(current.get("pending_folders"))

    def prepare(
        self,
        sources: Sequence[Source],
        overall: ScanStats,
        source_policies: Optional[Mapping[int, SourceScanPolicy]] = None,
        metadata_index_hash: str = "",
    ) -> ScanStats:
        self._source_ids = [int(source.id) for source in sources]
        self._signature = self._scan_signature(
            sources, source_policies, metadata_index_hash
        )
        state = self._read()
        if state and self._is_valid(state, sources):
            self._state = state
            self.resumed = bool(
                state.get("completed_source_ids") or state.get("current_source")
            )
            restored = _stats_from_dict(state.get("overall"), overall.started_at)
            restored.cancelled = False
            restored.finished_at = None
            restored.duration_seconds = 0.0
            if self.resumed:
                self._log(
                    "info",
                    "Resuming interrupted scan from a saved folder checkpoint",
                )
            return restored

        if state:
            self._log(
                "info",
                "Discarded an expired or incompatible scan checkpoint",
            )
            self.clear()
        self._state = {
            "version": CHECKPOINT_VERSION,
            "signature": self._signature,
            "source_ids": list(self._source_ids),
            "completed_source_ids": [],
            "overall": _stats_to_dict(overall),
            "current_source": None,
        }
        self._write()
        return overall

    @property
    def active(self) -> bool:
        return bool(self._state and self._signature and self._source_ids)

    def completed_source_ids(self) -> Set[int]:
        if not self.active:
            return set()
        values = self._state.get("completed_source_ids") or []
        return {int(value) for value in values}

    def current_source(self, source: Source) -> Optional[Dict[str, Any]]:
        if not self.active:
            return None
        current = self._state.get("current_source")
        if not isinstance(current, dict):
            return None
        if int(current.get("source_id", -1)) != int(source.id):
            return None
        return current

    def begin_source(
        self,
        source: Source,
        scan_started_at: str,
        pending_folders: Sequence[Tuple[str, str, str]],
        stats: ScanStats,
        traversal_complete: bool,
    ) -> None:
        if not self.active:
            return
        self._state["current_source"] = {
            "source_id": int(source.id),
            "source_uri": normalize_uri(source.uri, directory=True),
            "scan_started_at": str(scan_started_at),
            "pending_folders": [list(item) for item in pending_folders],
            "stats": _stats_to_dict(stats),
            "traversal_complete": bool(traversal_complete),
        }
        self._write()

    def update_source(
        self,
        source: Source,
        scan_started_at: str,
        pending_folders: Sequence[Tuple[str, str, str]],
        stats: ScanStats,
        traversal_complete: bool,
    ) -> None:
        self.begin_source(
            source,
            scan_started_at,
            pending_folders,
            stats,
            traversal_complete,
        )

    def restore_source(
        self,
        source: Source,
    ) -> Optional[Tuple[str, List[Tuple[str, str, str]], ScanStats, bool]]:
        current = self.current_source(source)
        if current is None:
            return None
        pending = [tuple(item) for item in current.get("pending_folders") or []]
        stats = _stats_from_dict(current.get("stats"), current.get("scan_started_at"))
        stats.cancelled = False
        stats.finished_at = None
        stats.duration_seconds = 0.0
        return (
            str(current["scan_started_at"]),
            pending,
            stats,
            bool(current.get("traversal_complete", True)),
        )

    def current_stats(self) -> Optional[ScanStats]:
        if not self.active:
            return None
        current = self._state.get("current_source")
        if not isinstance(current, dict):
            return None
        return _stats_from_dict(current.get("stats"), current.get("scan_started_at"))

    def complete_source(self, source_id: int, overall: ScanStats) -> None:
        if not self.active:
            return
        completed = [int(value) for value in self._state.get("completed_source_ids") or []]
        if int(source_id) not in completed:
            completed.append(int(source_id))
        self._state["completed_source_ids"] = completed
        self._state["overall"] = _stats_to_dict(overall)
        self._state["current_source"] = None
        self._write()

    def finish(self) -> None:
        self.clear()
