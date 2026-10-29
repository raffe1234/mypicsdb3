"""Ensure the Kodi screensaver advances to new random batches only when desired."""
from __future__ import annotations

import importlib.util
import itertools
import sys
import types
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "randomize, fail_refresh",
    [(True, False), (False, False), (True, True)],
)
def test_screensaver_requeries_after_completed_random_batch(
    monkeypatch, randomize, fail_refresh
):
    shown = []
    provider_calls = []

    class Monitor:
        deactivated = False

        def abortRequested(self):
            return len(shown) >= 3

        def waitForAbort(self, _duration):
            return False

    class Window:
        exit_requested = False

        def addControl(self, _item):
            pass

        def getWidth(self):
            return 1280

        def getHeight(self):
            return 720

        def show(self):
            pass

        def close(self):
            pass

    class Image:
        def __init__(self, *args, **kwargs):
            pass

        def setImage(self, uri, _use_cache):
            shown.append(uri)

    monkeypatch.setitem(sys.modules, "xbmc", types.SimpleNamespace(
        LOGINFO=1, LOGWARNING=2, LOGERROR=3,
        Monitor=Monitor, log=lambda *_: None,
    ))
    monkeypatch.setitem(sys.modules, "xbmcaddon", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcvfs", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcgui", types.SimpleNamespace(
        WindowDialog=Window, ControlImage=Image,
        getScreenWidth=lambda: 1280, getScreenHeight=lambda: 720,
    ))

    script = (Path(__file__).resolve().parents[1]
              / "screensaver.mypicsdb3" / "default.py")
    spec = importlib.util.spec_from_file_location("mypicsdb3_cycle_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    ticks = itertools.count()
    module.time = types.SimpleNamespace(monotonic=lambda: next(ticks) * 3.0)
    monkeypatch.setattr(module, "_add_opaque_background", lambda *_: None)
    monkeypatch.setattr(module, "_logger", lambda *_a, **_kw: None)

    class Picture:
        def __init__(self, picture_id):
            self.id = picture_id
            self.uri = "image-%s.jpg" % picture_id
            self.filename = self.uri

    class Provider:
        def pictures(self, *args, **kwargs):
            provider_calls.append(kwargs)
            n = len(provider_calls)
            if n > 1 and fail_refresh:
                raise SourceError("temporary database problem")
            return [Picture(n * 2 - 1), Picture(n * 2)]

    provider = Provider()
    monkeypatch.setattr(module, "_provider", lambda _: provider)

    class Settings:
        values = {
            "source_type": "manual", "source_id": "1", "source_name": "All",
            "max_items": "2", "slide_seconds": "2", "show_filename": "false",
            "randomize": "true" if randomize else "false",
        }

        def getSetting(self, key):
            return self.values[key]

    class SourceError(Exception):
        pass

    core = {
        "normalize_limit": int, "normalize_seconds": int, "error": SourceError,
    }
    module._run_screensaver(core, Settings())

    if randomize:
        assert shown[:2] == ["image-1.jpg", "image-2.jpg"]
        assert shown[2] in (
            {"image-1.jpg", "image-2.jpg"}
            if fail_refresh else {"image-3.jpg"}
        )
        assert len(provider_calls) == 2
    else:
        assert shown == ["image-1.jpg", "image-2.jpg", "image-1.jpg"]
        assert len(provider_calls) == 1
