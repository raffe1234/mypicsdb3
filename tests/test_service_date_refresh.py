from __future__ import annotations

from datetime import date

from mypicsdb3.service_loop import ServiceLoop


class FakeLog:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)


class FakeKodi:
    def __init__(self):
        self.log = FakeLog()
        self.refreshes = 0

    def abort_monitor(self):
        return object()

    def refresh_date_sensitive_views(self):
        self.refreshes += 1


def test_date_change_refreshes_date_sensitive_views_once() -> None:
    dates = iter((date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 19)))
    kodi = FakeKodi()
    loop = ServiceLoop(kodi, date_provider=lambda: next(dates))

    loop._refresh_after_date_change()
    loop._refresh_after_date_change()

    assert kodi.refreshes == 1
    assert kodi.log.messages == [
        "Local date changed from 2026-07-18 to 2026-07-19; refreshing date-sensitive views"
    ]
