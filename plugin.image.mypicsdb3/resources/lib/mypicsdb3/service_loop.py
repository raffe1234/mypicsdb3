from __future__ import annotations

import time
from datetime import date
from typing import Callable

from .db import Catalog, DatabaseEngine
from .filesystem import KodiFilesystem
from .scanner import Scanner


class ServiceLoop:
    def __init__(self, kodi_context, date_provider: Callable[[], date] = date.today):
        self.kodi = kodi_context
        self.monitor = self.kodi.abort_monitor()
        self.next_scan_at = 0.0
        self.date_provider = date_provider
        self.current_date = self.date_provider()

    def _refresh_after_date_change(self) -> None:
        today = self.date_provider()
        if today == self.current_date:
            return
        previous_date = self.current_date
        self.current_date = today
        self.kodi.log.info(
            "Local date changed from %s to %s; refreshing date-sensitive views",
            previous_date.isoformat(),
            today.isoformat(),
        )
        self.kodi.refresh_date_sensitive_views()

    def _runtime_parts(self):
        settings = self.kodi.refresh_settings()
        engine = DatabaseEngine(settings, self.kodi.log)
        catalog = Catalog(engine, self.kodi.log)
        catalog.initialize()
        filesystem = KodiFilesystem(self.kodi.profile_path.rstrip("/\\") + "/temp")
        return settings, catalog, filesystem

    def run(self):
        settings, catalog, filesystem = self._runtime_parts()
        try:
            catalog.sync_sources(self.kodi.kodi_picture_sources())
        except Exception as exc:
            self.kodi.log.warning("Initial source synchronization failed: %s", exc)
        self.next_scan_at = time.monotonic() + settings.startup_delay_seconds
        while not self.monitor.abortRequested():
            self._refresh_after_date_change()
            settings = self.kodi.refresh_settings()
            now = time.monotonic()
            if settings.auto_scan and now >= self.next_scan_at:
                if not (settings.pause_during_playback and self.kodi.is_playing()):
                    try:
                        engine = DatabaseEngine(settings, self.kodi.log)
                        catalog = Catalog(engine, self.kodi.log)
                        catalog.initialize()
                        scanner = Scanner(
                            catalog,
                            filesystem,
                            settings,
                            self.kodi.log,
                            cancelled=self.monitor.abortRequested,
                        )
                        stats = scanner.scan_sources()
                        self.kodi.log.info("Automatic scan finished: %d pictures, %d errors", stats.pictures_seen, stats.errors)
                    except Exception as exc:
                        self.kodi.log.error("Automatic scan failed: %s", exc)
                    self.next_scan_at = time.monotonic() + settings.scan_interval_hours * 3600
            if self.monitor.waitForAbort(5):
                break
