from __future__ import annotations

import types

import mypicsdb3.kodi as kodi_module


class FakeWindow:
    def __init__(self):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, "")

    def setProperty(self, key, value):
        self.properties[key] = value

    def clearProperty(self, key):
        self.properties.pop(key, None)


class FakeLog:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


def make_context(monkeypatch):
    window = FakeWindow()
    monkeypatch.setattr(
        kodi_module,
        "xbmcgui",
        types.SimpleNamespace(Window=lambda _window_id: window),
    )
    context = object.__new__(kodi_module.KodiContext)
    context.log = FakeLog()
    return context, window


def test_scan_state_is_shared_and_cancelled_by_matching_token(monkeypatch) -> None:
    context, window = make_context(monkeypatch)

    context.begin_scan_status("scan-1", "automatic")
    context.update_scan_status(
        "scan-1",
        "Photographs",
        "smb://nas/photos/image.nef",
        123,
        80,
        43,
        10,
        5,
        2,
    )

    status = context.scan_status()
    assert status["token"] == "scan-1"
    assert status["kind"] == "automatic"
    assert status["state"] == "running"
    assert status["source"] == "Photographs"
    assert status["path"].endswith("image.nef")
    assert status["pictures_seen"] == 123
    assert status["pictures_unchanged"] == 80
    assert status["metadata_reads"] == 43
    assert status["pictures_added"] == 10
    assert status["pictures_updated"] == 5
    assert status["errors"] == 2

    assert context.request_scan_cancel() is True
    assert context.scan_cancel_requested("scan-1") is True
    assert context.scan_status()["state"] == "cancelling"

    context.finish_scan_status("other-scan")
    assert context.scan_status()["token"] == "scan-1"

    context.finish_scan_status("scan-1")
    assert context.scan_status() == {}
    assert window.getProperty(kodi_module.SCAN_CANCEL_PROPERTY) == ""


def test_stale_progress_does_not_replace_newer_scan(monkeypatch) -> None:
    context, _window = make_context(monkeypatch)

    context.begin_scan_status("scan-new", "manual")
    context.update_scan_status("scan-old", "Old", "old.jpg", 999)

    status = context.scan_status()
    assert status["token"] == "scan-new"
    assert status["pictures_seen"] == 0
