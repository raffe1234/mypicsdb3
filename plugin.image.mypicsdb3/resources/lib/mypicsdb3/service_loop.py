from __future__ import annotations

import time
from datetime import date
from typing import Callable

from .db import Catalog, DatabaseEngine
from .filesystem import KodiFilesystem
from .scanner import Scanner


DATE_REFRESH_DELAY_SECONDS = 60.0
DATE_REFRESH_RETRY_SECONDS = 15.0


class ServiceLoop:
    def __init__(
        self,
        kodi_context,
        date_provider: Callable[[], date] = date.today,
        monotonic_provider: Callable[[], float] = time.monotonic,
    ):
        self.kodi = kodi_context
        self.monitor = self.kodi.abort_monitor()
        self.next_scan_at = 0.0
        self.date_provider = date_provider
        self.monotonic_provider = monotonic_provider
        self.current_date = self.date_provider()
        self.pending_date_refresh = False
        self.date_refresh_not_before = 0.0
        self.date_refresh_deferred_logged = False

    def _refresh_after_date_change(self) -> None:
        today = self.date_provider()
        now = self.monotonic_provider()
        if today != self.current_date:
            previous_date = self.current_date
            self.current_date = today
            self.pending_date_refresh = True
            self.date_refresh_not_before = now + DATE_REFRESH_DELAY_SECONDS
            self.date_refresh_deferred_logged = False
            self.kodi.log.info(
                "Local date changed from %s to %s; queued date-sensitive view refresh",
                previous_date.isoformat(),
                today.isoformat(),
            )

        if not self.pending_date_refresh or now < self.date_refresh_not_before:
            return

        try:
            refreshed = self.kodi.refresh_date_sensitive_views()
        except Exception as exc:
            self.kodi.log.warning(
                "Date-sensitive view refresh failed and will be retried: %s",
                exc,
            )
            self.date_refresh_not_before = now + DATE_REFRESH_RETRY_SECONDS
            return

        if refreshed:
            self.pending_date_refresh = False
            self.date_refresh_deferred_logged = False
            self.kodi.log.info("Date-sensitive view refresh completed")
        else:
            if not self.date_refresh_deferred_logged:
                self.kodi.log.info(
                    "Date-sensitive view refresh deferred until Kodi is idle"
                )
                self.date_refresh_deferred_logged = True
            self.date_refresh_not_before = now + DATE_REFRESH_RETRY_SECONDS

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
