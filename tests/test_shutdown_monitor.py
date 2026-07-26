from __future__ import annotations

from types import SimpleNamespace

from mypicsdb3.kodi import create_abort_monitor


class FakeNativeMonitor:
    def __init__(self):
        self.native_abort = False
        self.wait_calls = []

    def abortRequested(self):
        return self.native_abort

    def waitForAbort(self, timeout):
        self.wait_calls.append(timeout)
        return self.native_abort


def make_monitor():
    return create_abort_monitor(SimpleNamespace(Monitor=FakeNativeMonitor))


def test_system_onquit_is_treated_as_an_abort_request() -> None:
    monitor = make_monitor()

    monitor.onNotification("xbmc", "System.OnQuit", '{"exitcode":0}')

    assert monitor.abortRequested() is True
    assert monitor.waitForAbort(60) is True
    assert monitor.wait_calls == []


def test_system_onrestart_is_treated_as_an_abort_request() -> None:
    monitor = make_monitor()

    monitor.onNotification("xbmc", "System.OnRestart", "null")

    assert monitor.abortRequested() is True


def test_unrelated_notifications_do_not_stop_the_service() -> None:
    monitor = make_monitor()

    monitor.onNotification("xbmc", "Player.OnStop", "{}")

    assert monitor.abortRequested() is False
    assert monitor.waitForAbort(0.5) is False
    assert monitor.wait_calls == [0.5]


def test_native_monitor_abort_is_still_honoured() -> None:
    monitor = make_monitor()
    monitor.native_abort = True

    assert monitor.abortRequested() is True
    assert monitor.waitForAbort(0.5) is True
