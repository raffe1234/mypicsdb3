from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Tuple

from .utils import parse_bool, parse_int, split_csv, split_pipe


@dataclass(frozen=True)
class Settings:
    profile_path: str
    database_backend: str = "sqlite"
    widget_limit: int = 15
    browser_page_size: int = 100
    show_notifications: bool = True
    auto_scan: bool = False
    scan_interval_hours: int = 24
    startup_delay_seconds: int = 60
    pause_during_playback: bool = True
    extensions: Tuple[str, ...] = ("jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif", "avif")
    exclude_fragments: Tuple[str, ...] = ("@eadir", ".thumbnails", "#recycle", "@recycle")
    exclude_hidden: bool = True
    batch_size: int = 100
    read_xmp: bool = True
    read_iptc: bool = True
    store_gps: bool = False
    metadata_prefix_mb: int = 4
    deep_metadata_max_mb: int = 64
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "mypicsdb3"
    mysql_username: str = "kodi"
    mysql_password: str = ""
    mysql_auto_create: bool = False
    mysql_connect_timeout: int = 5
    missing_retention_days: int = 30
    debug_logging: bool = False

    @property
    def sqlite_path(self) -> str:
        return self.profile_path.rstrip("/\\") + "/mypicsdb3.sqlite"


def from_getter(getter: Callable[[str], Any], profile_path: str) -> Settings:
    backend = str(getter("database_backend") or "sqlite").strip().lower()
    if backend not in {"sqlite", "mysql"}:
        backend = "sqlite"
    return Settings(
        profile_path=profile_path,
        database_backend=backend,
        widget_limit=parse_int(getter("widget_limit"), 15, 1, 100),
        browser_page_size=parse_int(getter("browser_page_size"), 100, 10, 500),
        show_notifications=parse_bool(getter("show_notifications"), True),
        auto_scan=parse_bool(getter("auto_scan"), False),
        scan_interval_hours=parse_int(getter("scan_interval_hours"), 24, 1, 720),
        startup_delay_seconds=parse_int(getter("startup_delay_seconds"), 60, 0, 3600),
        pause_during_playback=parse_bool(getter("pause_during_playback"), True),
        extensions=split_csv(str(getter("extensions") or "jpg,jpeg,png,gif,bmp,tif,tiff,webp,heic,heif,avif")),
        exclude_fragments=split_pipe(str(getter("exclude_fragments") or "")),
        exclude_hidden=parse_bool(getter("exclude_hidden"), True),
        batch_size=parse_int(getter("batch_size"), 100, 10, 2000),
        read_xmp=parse_bool(getter("read_xmp"), True),
        read_iptc=parse_bool(getter("read_iptc"), True),
        store_gps=parse_bool(getter("store_gps"), False),
        metadata_prefix_mb=parse_int(getter("metadata_prefix_mb"), 4, 1, 32),
        deep_metadata_max_mb=parse_int(getter("deep_metadata_max_mb"), 64, 1, 1024),
        mysql_host=str(getter("mysql_host") or "127.0.0.1").strip(),
        mysql_port=parse_int(getter("mysql_port"), 3306, 1, 65535),
        mysql_database=str(getter("mysql_database") or "mypicsdb3").strip(),
        mysql_username=str(getter("mysql_username") or "kodi").strip(),
        mysql_password=str(getter("mysql_password") or ""),
        mysql_auto_create=parse_bool(getter("mysql_auto_create"), False),
        mysql_connect_timeout=parse_int(getter("mysql_connect_timeout"), 5, 1, 60),
        missing_retention_days=parse_int(getter("missing_retention_days"), 30, 0, 3650),
        debug_logging=parse_bool(getter("debug_logging"), False),
    )
