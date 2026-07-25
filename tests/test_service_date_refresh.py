from __future__ import annotations

from datetime import date

from mypicsdb3.service_loop import (
    DATE_REFRESH_DELAY_SECONDS,
    DATE_REFRESH_RETRY_SECONDS,
    ServiceLoop,
)


class FakeLog:
    def __init__(self):
        self.messages = []
        self.warnings = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


class FakeKodi:
    def __init__(self, refresh_results=None):
        self.log = FakeLog()
        self.refreshes = 0
        self.refresh_results = iter(refresh_results or (True,))

    def abort_monitor(self):
        return object()

    def refresh_date_sensitive_views(self):
        self.refreshes += 1
        result = next(self.refresh_results)
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_date_change_queues_refresh_and_waits_for_grace_period() -> None:
    dates = iter((date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 19)))
    clock = Clock()
    kodi = FakeKodi()
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: next(dates),
        monotonic_provider=clock,
    )

    loop._refresh_after_date_change()
    assert kodi.refreshes == 0
    assert loop.pending_date_refresh is True

    clock.advance(DATE_REFRESH_DELAY_SECONDS)
    loop._refresh_after_date_change()

    assert kodi.refreshes == 1
    assert loop.pending_date_refresh is False
    assert kodi.log.messages == [
        "Local date changed from 2026-07-18 to 2026-07-19; queued date-sensitive view refresh",
        "Date-sensitive view refresh completed",
    ]


def test_unsafe_refresh_is_retried_later() -> None:
    dates = iter(
        (
            date(2026, 7, 18),
            date(2026, 7, 19),
            date(2026, 7, 19),
            date(2026, 7, 19),
        )
    )
    clock = Clock()
    kodi = FakeKodi(refresh_results=(False, True))
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: next(dates),
        monotonic_provider=clock,
    )

    loop._refresh_after_date_change()
    clock.advance(DATE_REFRESH_DELAY_SECONDS)
    loop._refresh_after_date_change()

    assert kodi.refreshes == 1
    assert loop.pending_date_refresh is True
    assert kodi.log.messages[-1] == (
        "Date-sensitive view refresh deferred until Kodi is idle"
    )

    clock.advance(DATE_REFRESH_RETRY_SECONDS)
    loop._refresh_after_date_change()

    assert kodi.refreshes == 2
    assert loop.pending_date_refresh is False


def test_refresh_exception_keeps_request_pending() -> None:
    dates = iter(
        (
            date(2026, 7, 18),
            date(2026, 7, 19),
            date(2026, 7, 19),
            date(2026, 7, 19),
        )
    )
    clock = Clock()
    kodi = FakeKodi(refresh_results=(RuntimeError("GUI busy"), True))
    loop = ServiceLoop(
        kodi,
        date_provider=lambda: next(dates),
        monotonic_provider=clock,
    )

    loop._refresh_after_date_change()
    clock.advance(DATE_REFRESH_DELAY_SECONDS)
    loop._refresh_after_date_change()

    assert loop.pending_date_refresh is True
    assert kodi.log.warnings == [
        "Date-sensitive view refresh failed and will be retried: GUI busy"
    ]

    clock.advance(DATE_REFRESH_RETRY_SECONDS)
    loop._refresh_after_date_change()

    assert loop.pending_date_refresh is False
