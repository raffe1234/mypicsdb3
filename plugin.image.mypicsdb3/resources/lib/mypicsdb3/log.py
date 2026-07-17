from __future__ import annotations

import logging
from typing import Optional


class Logger:
    def __init__(self, name: str = "MyPicsDB3", debug: bool = False, kodi_module=None):
        self.name = name
        self.debug_enabled = debug
        self.kodi = kodi_module
        self.standard = logging.getLogger(name)

    def _write(self, level: str, message: str) -> None:
        text = "[%s] %s" % (self.name, message)
        if self.kodi is not None:
            kodi_level = {
                "debug": getattr(self.kodi, "LOGDEBUG", 0),
                "info": getattr(self.kodi, "LOGINFO", 1),
                "warning": getattr(self.kodi, "LOGWARNING", 2),
                "error": getattr(self.kodi, "LOGERROR", 3),
            }[level]
            self.kodi.log(text, kodi_level)
        else:
            getattr(self.standard, level)(text)

    def debug(self, message: str, *args) -> None:
        if self.debug_enabled:
            self._write("debug", message % args if args else message)

    def info(self, message: str, *args) -> None:
        self._write("info", message % args if args else message)

    def warning(self, message: str, *args) -> None:
        self._write("warning", message % args if args else message)

    def error(self, message: str, *args) -> None:
        self._write("error", message % args if args else message)

    def exception(self, message: str, *args) -> None:
        self.error(message, *args)
