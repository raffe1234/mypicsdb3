from __future__ import annotations

import time
from datetime import date
from typing import Callable

from .db import Catalog, DatabaseEngine
from .filesystem import KodiFilesystem
from .scanner import Scanner


DATE_REFRESH_DELAY_SECONDS = 60.0
DATE_REFRESH_RETRY_SECONDS = 15.0
SERVICE_POLL_SECONDS = 0.5
MAINTENANCE_INTERVAL_SECONDS = 5.0
VIDEO_IDLE_CLEAR_POLLS = 3
MIXED_SLIDESHOW_STARTUP_IDLE_POLLS = 20


class MixedSlideshowVideoMonitor:
    """Advance Kodi's picture playlist after an indexed video finishes."""

    def __init__(self, kodi_context, catalog: Catalog):
        self.kodi = kodi_context
        self.catalog = catalog
        self.active_video_uri = ""
        self.idle_polls = 0
        self.session_seen_player = False
        self.failure_logged = False

    def _active_players(self):
        result = self.kodi.execute_jsonrpc("Player.GetActivePlayers")
        return result if isinstance(result, list) else []

    def _reset_state(self) -> None:
        self.active_video_uri = ""
        self.idle_polls = 0
        self.session_seen_player = False

    def _clear_session(self) -> None:
        self.kodi.set_mixed_slideshow_active(False)
        self._reset_state()

    def tick(self) -> None:
        try:
            if not self.kodi.mixed_slideshow_active():
                self._reset_state()
                self.failure_logged = False
                return

            players = self._active_players()
            self.failure_logged = False
            by_type = {
                str(player.get("type") or ""): int(player.get("playerid", -1))
                for player in players
                if isinstance(player, dict)
            }
            relevant_player_active = "picture" in by_type or "video" in by_type
            if not relevant_player_active:
                self.idle_polls += 1
                idle_limit = (
                    VIDEO_IDLE_CLEAR_POLLS
                    if self.session_seen_player
                    else MIXED_SLIDESHOW_STARTUP_IDLE_POLLS
                )
                if self.idle_polls >= idle_limit:
                    self._clear_session()
                return

            self.session_seen_player = True
            self.idle_polls = 0

            if "video" in by_type:
                playing_file = self.kodi.playing_file()
                if playing_file == self.active_video_uri:
                    return
                self.active_video_uri = ""
                if playing_file and self.catalog.media_type_for_uri(playing_file) == "video":
                    self.active_video_uri = playing_file
                return

            if self.active_video_uri and "picture" in by_type:
                self.kodi.execute_jsonrpc(
                    "Player.GoTo",
                    {"playerid": by_type["picture"], "to": "next"},
                )
                self.kodi.log.info(
                    "Advanced mixed slideshow after video finished: %s",
                    self.active_video_uri,
                )
                self.active_video_uri = ""
        except Exception as exc:
            if not self.failure_logged:
                self.kodi.log.warning(
                    "Mixed slideshow video monitor failed: %s",
                    exc,
                )
                self.failure_logged = True


class ServiceLoop:
    def __init__(
        self,
        kodi_context,
        date_provider: Callable[[], date] = date.today,
        monotonic_provider: Callable[[], float] = time.monotonic,
        monitor=None,
    ):
        self.kodi = kodi_context
        self.monitor = monitor or self.kodi.abort_monitor()
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

    def _abort_requested(self) -> bool:
        return bool(self.monitor and self.monitor.abortRequested())

    def run(self):
        if self._abort_requested():
            return
        settings, catalog, filesystem = self._runtime_parts()
        if self._abort_requested():
            return
        try:
            catalog.sync_sources(self.kodi.kodi_picture_sources())
        except Exception as exc:
            self.kodi.log.warning("Initial source synchronization failed: %s", exc)
        now = self.monotonic_provider()
        self.next_scan_at = now + settings.startup_delay_seconds
        next_maintenance_at = now
        slideshow_monitor = MixedSlideshowVideoMonitor(self.kodi, catalog)

        while not self._abort_requested():
            slideshow_monitor.tick()
            now = self.monotonic_provider()
            if now >= next_maintenance_at:
                self._refresh_after_date_change()
                settings = self.kodi.refresh_settings()
                if self._abort_requested():
                    break
                if settings.auto_scan and now >= self.next_scan_at:
                    if not (settings.pause_during_playback and self.kodi.is_playing()):
                        if self._abort_requested():
                            break
                        try:
                            engine = DatabaseEngine(settings, self.kodi.log)
                            catalog = Catalog(engine, self.kodi.log)
                            catalog.initialize()
                            slideshow_monitor.catalog = catalog
                            scanner = Scanner(
                                catalog,
                                filesystem,
                                settings,
                                self.kodi.log,
                                cancelled=self._abort_requested,
                            )
                            stats = scanner.scan_sources()
                            if stats.cancelled:
                                self.kodi.log.info("Automatic scan cancelled")
                            else:
                                self.kodi.log.info(
                                    "Automatic scan finished: %d pictures, %d errors",
                                    stats.pictures_seen,
                                    stats.errors,
                                )
                        except Exception as exc:
                            self.kodi.log.error("Automatic scan failed: %s", exc)
                        if self._abort_requested():
                            break
                        self.next_scan_at = (
                            self.monotonic_provider()
                            + settings.scan_interval_hours * 3600
                        )
                next_maintenance_at = now + MAINTENANCE_INTERVAL_SECONDS
            if self.monitor.waitForAbort(SERVICE_POLL_SECONDS):
                break
