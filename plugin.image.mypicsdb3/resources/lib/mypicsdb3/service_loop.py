from __future__ import annotations

import os
import time
import uuid
from datetime import date, datetime, timezone
from typing import Callable

from .db import Catalog, DatabaseEngine
from .db.migrations import MigrationLockError
from .filesystem import KodiFilesystem
from .music_slideshow import stop_music_player
from .scan_checkpoint import CHECKPOINT_FILENAME
from .scanner import LAST_COMPLETE_SCAN_META_KEY, ScanAlreadyRunning, Scanner


DATE_REFRESH_DELAY_SECONDS = 60.0
DATE_REFRESH_RETRY_SECONDS = 15.0
SERVICE_POLL_SECONDS = 0.5
MAINTENANCE_INTERVAL_SECONDS = 5.0
VIDEO_IDLE_CLEAR_POLLS = 3
MIXED_SLIDESHOW_STARTUP_IDLE_POLLS = 20
DATABASE_BUSY_RETRY_SECONDS = 2.0
SCAN_BUSY_RETRY_SECONDS = 60.0
MUSIC_SLIDESHOW_STARTUP_IDLE_POLLS = 20
MUSIC_SLIDESHOW_END_IDLE_POLLS = 3


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
        self.kodi.log.debug("Mixed slideshow monitor cleared idle session")
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
                    self.kodi.log.debug("Mixed slideshow monitor detected indexed video")
                elif playing_file:
                    self.kodi.log.debug(
                        "Mixed slideshow monitor ignored unindexed video player item"
                    )
                return

            if self.active_video_uri and "picture" in by_type:
                self.kodi.execute_jsonrpc(
                    "Player.GoTo",
                    {"playerid": by_type["picture"], "to": "next"},
                )
                self.kodi.log.info(
                    "Advanced mixed slideshow after indexed video finished"
                )
                self.active_video_uri = ""
        except Exception as exc:
            if not self.failure_logged:
                self.kodi.log.warning(
                    "Mixed slideshow video monitor failed: %s",
                    exc,
                )
                self.failure_logged = True


class MusicSlideshowMonitor:
    """Stop only the music queue owned by a finished MyPicsDB slideshow."""

    def __init__(self, kodi_context):
        self.kodi = kodi_context
        self.token = ""
        self.seen_picture_player = False
        self.idle_polls = 0
        self.failure_logged = False

    def _reset(self) -> None:
        self.token = ""
        self.seen_picture_player = False
        self.idle_polls = 0

    def tick(self) -> None:
        try:
            session = self.kodi.music_slideshow_session()
            token = str(session.get("token") or "")
            if not token:
                self._reset()
                self.failure_logged = False
                return
            if token != self.token:
                self.token = token
                self.seen_picture_player = False
                self.idle_polls = 0

            result = self.kodi.execute_jsonrpc("Player.GetActivePlayers")
            players = result if isinstance(result, list) else []
            player_types = {
                str(player.get("type") or "")
                for player in players
                if isinstance(player, dict)
            }
            self.failure_logged = False
            if "picture" in player_types:
                self.seen_picture_player = True
                self.idle_polls = 0
                return

            self.idle_polls += 1
            idle_limit = (
                MUSIC_SLIDESHOW_END_IDLE_POLLS
                if self.seen_picture_player
                else MUSIC_SLIDESHOW_STARTUP_IDLE_POLLS
            )
            if self.idle_polls < idle_limit:
                return

            expected = str(session.get("playlist_fingerprint") or "")
            current = self.kodi.music_playlist_fingerprint()
            if "audio" in player_types and expected and current == expected:
                stop_music_player(
                    self.kodi, logger=self.kodi.log, active_players=players
                )
            elif "audio" in player_types:
                self.kodi.log.info(
                    "Music slideshow ended but Kodi's music queue changed; "
                    "replacement audio was left playing"
                )
            self.kodi.clear_music_slideshow_session(token)
            self._reset()
        except Exception as exc:
            if not self.failure_logged:
                self.kodi.log.warning("Music slideshow monitor failed: %s", exc)
                self.failure_logged = True


class ServiceLoop:
    def __init__(
        self,
        kodi_context,
        date_provider: Callable[[], date] = date.today,
        monotonic_provider: Callable[[], float] = time.monotonic,
        utcnow_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monitor=None,
    ):
        self.kodi = kodi_context
        self.monitor = monitor or self.kodi.abort_monitor()
        self.next_scan_at = 0.0
        self.date_provider = date_provider
        self.monotonic_provider = monotonic_provider
        self.utcnow_provider = utcnow_provider
        self.current_date = self.date_provider()
        self.pending_date_refresh = False
        self.date_refresh_not_before = 0.0
        self.date_refresh_deferred_logged = False
        self.random_home_refresh_hours = 0
        self.next_random_home_refresh_at = 0.0

    def _initial_scan_delay(self, settings, catalog) -> float:
        """Return seconds until the first automatic scan in this service run.

        A local interrupted-scan checkpoint deliberately wins: resuming an
        unfinished traversal should not wait the normal 24-hour cadence. With
        no checkpoint, however, service/Kodi restarts must not reset the scan
        clock. The last *complete* full scan is persisted in catalogue meta.
        """

        startup_delay = max(0.0, float(settings.startup_delay_seconds))
        checkpoint_path = os.path.join(
            str(getattr(settings, "profile_path", self.kodi.profile_path)).rstrip("/\\"),
            CHECKPOINT_FILENAME,
        )
        if os.path.isfile(checkpoint_path):
            self.kodi.log.info(
                "Interrupted scan checkpoint found; resuming after %.0f-second startup delay",
                startup_delay,
            )
            return startup_delay

        getter = getattr(catalog, "meta_value", None)
        stored = getter(LAST_COMPLETE_SCAN_META_KEY) if callable(getter) else None
        if not stored:
            return startup_delay
        text = str(stored).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            completed_at = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return startup_delay
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        else:
            completed_at = completed_at.astimezone(timezone.utc)
        now_utc = self.utcnow_provider()
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)
        elapsed = max(0.0, (now_utc - completed_at).total_seconds())
        interval = max(1.0, float(settings.scan_interval_hours) * 3600.0)
        remaining = max(0.0, interval - elapsed)
        delay = max(startup_delay, remaining)
        if remaining > 0:
            self.kodi.log.info(
                "Automatic scan cadence preserved across restart; next scan due in %.1f hours",
                delay / 3600.0,
            )
        return delay

    def _maintain_random_home_refresh(self, settings, now: float) -> None:
        hours = max(
            1,
            min(720, int(getattr(settings, "random_home_refresh_hours", 2))),
        )
        interval_seconds = float(hours * 3600)

        if self.random_home_refresh_hours <= 0:
            self.random_home_refresh_hours = hours
            self.next_random_home_refresh_at = now + interval_seconds
            self.kodi.log.info(
                "Random home-screen refresh interval loaded: %d hours",
                hours,
            )
            return

        reason = ""
        if hours != self.random_home_refresh_hours:
            previous = self.random_home_refresh_hours
            self.random_home_refresh_hours = hours
            self.next_random_home_refresh_at = now + interval_seconds
            reason = "random home refresh interval changed"
            self.kodi.log.info(
                "Random home-screen refresh interval changed: %d -> %d hours",
                previous,
                hours,
            )
        elif now >= self.next_random_home_refresh_at:
            self.next_random_home_refresh_at = now + interval_seconds
            reason = "scheduled random home refresh"

        if not reason:
            return
        invalidator = getattr(self.kodi, "invalidate_random_home_widgets", None)
        if not callable(invalidator):
            return
        try:
            invalidator(reason)
        except Exception as exc:
            self.kodi.log.warning(
                "Could not refresh random home-screen widgets: %s",
                exc,
            )

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

    def _runtime_parts_when_ready(self):
        busy_logged = False
        while not self._abort_requested():
            try:
                return self._runtime_parts()
            except MigrationLockError as exc:
                if not busy_logged:
                    self.kodi.log.info(
                        "Database initialization is busy; retrying shortly: %s",
                        exc,
                    )
                    busy_logged = True
                if self.monitor.waitForAbort(DATABASE_BUSY_RETRY_SECONDS):
                    return None
        return None

    def run(self):
        if self._abort_requested():
            return
        runtime_parts = self._runtime_parts_when_ready()
        if runtime_parts is None:
            return
        settings, catalog, filesystem = runtime_parts
        previous_home_widget_limit = int(
            getattr(settings, "home_widget_limit", 10)
        )
        self.kodi.log.info(
            "Home-screen widget limit loaded: %d",
            previous_home_widget_limit,
        )
        if self._abort_requested():
            return
        try:
            catalog.sync_sources(self.kodi.kodi_picture_sources())
        except Exception as exc:
            self.kodi.log.warning("Initial source synchronization failed: %s", exc)
        now = self.monotonic_provider()
        self.next_scan_at = now + self._initial_scan_delay(settings, catalog)
        self._maintain_random_home_refresh(settings, now)
        next_maintenance_at = now
        slideshow_monitor = MixedSlideshowVideoMonitor(self.kodi, catalog)
        music_slideshow_monitor = MusicSlideshowMonitor(self.kodi)

        while not self._abort_requested():
            slideshow_monitor.tick()
            music_slideshow_monitor.tick()
            now = self.monotonic_provider()
            if now >= next_maintenance_at:
                self._refresh_after_date_change()
                settings = self.kodi.refresh_settings()
                self._maintain_random_home_refresh(settings, now)
                current_home_widget_limit = int(
                    getattr(settings, "home_widget_limit", 10)
                )
                if current_home_widget_limit != previous_home_widget_limit:
                    old_home_widget_limit = previous_home_widget_limit
                    previous_home_widget_limit = current_home_widget_limit
                    self.kodi.log.info(
                        "Home-screen widget limit changed: %d -> %d",
                        old_home_widget_limit,
                        current_home_widget_limit,
                    )
                    invalidator = getattr(
                        self.kodi, "invalidate_home_widgets", None
                    )
                    if callable(invalidator):
                        try:
                            invalidator("home widget limit changed")
                        except Exception as exc:
                            self.kodi.log.warning(
                                "Could not refresh home widgets after setting change: %s",
                                exc,
                            )
                if self._abort_requested():
                    break
                if settings.auto_scan and now >= self.next_scan_at:
                    if not (settings.pause_during_playback and self.kodi.is_playing()):
                        if self._abort_requested():
                            break
                        scan_token = uuid.uuid4().hex
                        scan_started = False
                        progress_dialog = None
                        last_progress_at = 0.0
                        user_cancelled = False
                        playback_paused = False
                        scan_busy = False

                        def close_progress_dialog() -> None:
                            nonlocal progress_dialog
                            if progress_dialog is None:
                                return
                            try:
                                progress_dialog.close()
                            except Exception:
                                pass
                            progress_dialog = None

                        def ensure_progress_dialog():
                            nonlocal progress_dialog
                            if self._abort_requested() or self.kodi.is_playing():
                                close_progress_dialog()
                                return None
                            if progress_dialog is not None:
                                return progress_dialog
                            creator = getattr(
                                self.kodi,
                                "create_background_progress",
                                None,
                            )
                            if callable(creator):
                                progress_dialog = creator(
                                    self.kodi.localize(30056, "MyPicsDB 3"),
                                    self.kodi.localize(32731, "Automatic scan"),
                                )
                            return progress_dialog

                        def begin_status(_stats) -> None:
                            nonlocal scan_started
                            scan_started = True
                            publisher = getattr(self.kodi, "begin_scan_status", None)
                            if callable(publisher):
                                publisher(scan_token, "automatic")
                            ensure_progress_dialog()

                        def scan_cancelled() -> bool:
                            nonlocal user_cancelled, playback_paused

                            def soft_cancelled() -> bool:
                                nonlocal user_cancelled
                                requested = getattr(
                                    self.kodi,
                                    "scan_cancel_requested",
                                    None,
                                )
                                user_cancelled = bool(
                                    callable(requested) and requested(scan_token)
                                )
                                return user_cancelled

                            if self._abort_requested() or soft_cancelled():
                                close_progress_dialog()
                                return True

                            while (
                                settings.pause_during_playback
                                and self.kodi.is_playing()
                                and not self._abort_requested()
                                and not soft_cancelled()
                            ):
                                close_progress_dialog()
                                if not playback_paused:
                                    playback_paused = True
                                    self.kodi.log.info(
                                        "Automatic scan paused during playback"
                                    )
                                if self.monitor.waitForAbort(1):
                                    return True

                            if self._abort_requested() or soft_cancelled():
                                close_progress_dialog()
                                return True

                            if playback_paused:
                                playback_paused = False
                                self.kodi.log.info(
                                    "Automatic scan resumed after playback"
                                )

                            if self.kodi.is_playing():
                                close_progress_dialog()
                            elif scan_started:
                                ensure_progress_dialog()
                            return False

                        def scan_progress(source, path, stats) -> None:
                            nonlocal last_progress_at
                            progress_now = self.monotonic_provider()
                            if (
                                progress_now - last_progress_at < 0.5
                                and int(stats.pictures_seen or 0) % 100
                            ):
                                return
                            last_progress_at = progress_now
                            publisher = getattr(
                                self.kodi,
                                "update_scan_status",
                                None,
                            )
                            if callable(publisher):
                                publisher(
                                    scan_token,
                                    source.label,
                                    path,
                                    stats.pictures_seen,
                                    getattr(stats, "pictures_unchanged", 0),
                                    getattr(stats, "metadata_reads", 0),
                                    getattr(stats, "pictures_added", 0),
                                    getattr(stats, "pictures_updated", 0),
                                    getattr(stats, "errors", 0),
                                )
                            dialog = ensure_progress_dialog()
                            if dialog is not None:
                                message = "%s\n%s\n%s: %d" % (
                                    source.label,
                                    path,
                                    self.kodi.localize(30047, "Pictures found"),
                                    stats.pictures_seen,
                                )
                                try:
                                    dialog.update(
                                        0,
                                        self.kodi.localize(30056, "MyPicsDB 3"),
                                        message,
                                    )
                                except Exception as exc:
                                    if not self._abort_requested():
                                        self.kodi.log.warning(
                                            "Automatic scan progress update failed: %s",
                                            exc,
                                        )
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
                                cancelled=scan_cancelled,
                                progress=scan_progress,
                                started=begin_status,
                            )
                            stats = scanner.scan_sources()
                            if (
                                int(getattr(stats, "pictures_added", 0) or 0)
                                + int(getattr(stats, "pictures_updated", 0) or 0)
                                + int(getattr(stats, "missing_marked", 0) or 0)
                                > 0
                            ):
                                invalidator = getattr(
                                    self.kodi, "invalidate_home_widgets", None
                                )
                                if callable(invalidator):
                                    try:
                                        invalidator("automatic scan changed pictures")
                                    except Exception as exc:
                                        self.kodi.log.warning(
                                            "Could not refresh home widgets after automatic scan: %s",
                                            exc,
                                        )
                            if stats.cancelled:
                                if user_cancelled:
                                    self.kodi.log.info(
                                        "Automatic scan cancelled by user"
                                    )
                                elif self._abort_requested():
                                    self.kodi.log.info(
                                        "Automatic scan interrupted because Kodi or the add-on service stopped"
                                    )
                                else:
                                    self.kodi.log.info("Automatic scan cancelled")
                            else:
                                self.kodi.log.info(
                                    "Automatic scan finished: %d pictures, %d errors",
                                    stats.pictures_seen,
                                    getattr(stats, "errors", 0),
                                )
                        except ScanAlreadyRunning:
                            scan_busy = True
                            self.kodi.log.info(
                                "Automatic scan skipped: another scan is already running; retrying in %d seconds",
                                int(SCAN_BUSY_RETRY_SECONDS),
                            )
                        except Exception as exc:
                            self.kodi.log.error("Automatic scan failed: %s", exc)
                        finally:
                            close_progress_dialog()
                            if scan_started:
                                finisher = getattr(
                                    self.kodi,
                                    "finish_scan_status",
                                    None,
                                )
                                if callable(finisher):
                                    try:
                                        finisher(scan_token)
                                    except Exception as exc:
                                        self.kodi.log.warning(
                                            "Could not clear automatic scan status: %s",
                                            exc,
                                        )
                        if self._abort_requested():
                            break
                        if scan_busy:
                            self.next_scan_at = (
                                self.monotonic_provider() + SCAN_BUSY_RETRY_SECONDS
                            )
                        else:
                            self.next_scan_at = (
                                self.monotonic_provider()
                                + settings.scan_interval_hours * 3600
                            )
                next_maintenance_at = now + MAINTENANCE_INTERVAL_SECONDS
            if self.monitor.waitForAbort(SERVICE_POLL_SECONDS):
                break
