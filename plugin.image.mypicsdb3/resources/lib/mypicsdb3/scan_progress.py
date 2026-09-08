"""Presentation-only scan estimates; never used to control traversal or writes."""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from .source_scan_policy import source_scan_policy_signature_payload
from .utils import normalize_uri, sha256_text


class ScanCountHistory:
    """One bounded record per source, in the existing catalogue meta table."""

    def __init__(self, catalog, logger=None):
        self.catalog = catalog
        self.logger = logger

    @staticmethod
    def key(source):
        return "scan-count-v1:%d" % int(source.id)

    @staticmethod
    def signature(source, policy):
        return sha256_text(json.dumps({
            "version": 1,
            "uri": normalize_uri(source.uri, directory=True),
            "policy": source_scan_policy_signature_payload(policy),
        }, sort_keys=True, separators=(",", ":")))

    def _warn(self, exc):
        if self.logger is not None:
            self.logger.warning("Scan count estimate unavailable: %s", exc)

    def load(self, source, policy) -> Optional[int]:
        try:
            raw = self.catalog.meta_value(self.key(source))
            data = json.loads(raw) if raw else {}
            count = data.get("count")
            if (data.get("signature") == self.signature(source, policy)
                    and type(count) is int and count >= 0):
                return count
        except Exception as exc:
            self._warn(exc)
        return None

    def save(self, source, policy, stats):
        # Only an error-free complete source traversal supplies a new reference.
        # The caller also checks the source's completed status, not just counts.
        if stats.cancelled or stats.errors or stats.sources_scanned != 1:
            return
        try:
            self.catalog.set_meta_value(self.key(source), json.dumps({
                "signature": self.signature(source, policy),
                "count": int(stats.pictures_seen),
                "completed_at": stats.finished_at,
            }, sort_keys=True, separators=(",", ":")))
        except Exception as exc:
            self._warn(exc)


class ScanProgressDisplay:
    """Current-session rate; pauses and time before resume are excluded."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started_at = None
        self.start_seen = 0
        self.paused_at = None
        self.paused_seconds = 0.0

    def start(self, stats):
        self.started_at = self.clock()
        self.start_seen = int(getattr(stats, "pictures_seen", 0) or 0)
        self.paused_at = None
        self.paused_seconds = 0.0

    def pause(self):
        if self.started_at is not None and self.paused_at is None:
            self.paused_at = self.clock()

    def resume(self):
        if self.paused_at is not None:
            self.paused_seconds += max(0.0, self.clock() - self.paused_at)
            self.paused_at = None

    def values(self, stats):
        now = self.paused_at if self.paused_at is not None else self.clock()
        elapsed = (max(0.0, now - self.started_at - self.paused_seconds)
                   if self.started_at is not None else 0.0)
        seen = int(getattr(stats, "pictures_seen", 0) or 0)
        total = getattr(stats, "estimated_total", None)
        percent = None
        seconds_left = None
        if total is not None and total > 0 and seen < total:
            percent = int(seen * 100 // total)
            session_seen = seen - self.start_seen
            if elapsed >= 10 and session_seen >= 10 and self.paused_at is None:
                seconds_left = (total - seen) * elapsed / session_seen
        return percent, seconds_left, elapsed

    def render(self, source, path, stats, text):
        percent, seconds_left, elapsed = self.values(stats)
        seen = int(getattr(stats, "pictures_seen", 0) or 0)
        added = int(getattr(stats, "pictures_added", 0) or 0)
        total = getattr(stats, "estimated_total", None)
        if percent is not None:
            status = text(33104, "Approx. %d%% — checked %d of about %d files") % (percent, seen, total)
        elif total is not None and total > 0 and seen >= total:
            status = text(33105, "Previous count reached — still scanning (%d files checked)") % seen
        else:
            status = text(33106, "Building scan estimate — %d files checked") % seen
        if seconds_left is None:
            timing = text(33107, "Active time: %d min; time left unknown") % int(elapsed // 60)
        else:
            timing = text(33108, "Approx. %d min left") % max(1, math.ceil(seconds_left / 60))
        message = "%s\n%s; %s\n%s\n%s" % (
            status, text(33109, "New files indexed: %d") % added, timing,
            source.label, path,
        )
        # Kodi's background dialog requires a numeric bar value. With no valid
        # estimate, reset it and explain the unknown state in the text.
        return percent if percent is not None else 0, message
