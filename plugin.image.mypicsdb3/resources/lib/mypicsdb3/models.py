from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Source:
    id: int
    label: str
    uri: str
    enabled: bool
    available: bool = True
    last_scan_at: Optional[str] = None
    last_scan_status: Optional[str] = None


@dataclass
class MetadataResult:
    taken_at: Optional[str] = None
    taken_source: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: Optional[int] = None
    mime_type: Optional[str] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    rating: Optional[int] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    keywords: List[str] = field(default_factory=list)
    location: Dict[str, str] = field(default_factory=dict)
    caption: Optional[str] = None
    metadata_hash: Optional[str] = None


@dataclass
class FileStat:
    size: int
    mtime: float


@dataclass
class ScanStats:
    scan_id: Optional[int] = None
    sources_total: int = 0
    sources_scanned: int = 0
    sources_unavailable: int = 0
    folders_seen: int = 0
    pictures_seen: int = 0
    pictures_added: int = 0
    pictures_updated: int = 0
    pictures_unchanged: int = 0
    missing_marked: int = 0
    errors: int = 0
    cancelled: bool = False
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    error_messages: List[str] = field(default_factory=list)

    def merge(self, other: "ScanStats") -> None:
        for name in (
            "sources_total", "sources_scanned", "sources_unavailable", "folders_seen",
            "pictures_seen", "pictures_added", "pictures_updated", "pictures_unchanged",
            "missing_marked", "errors"
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.cancelled = self.cancelled or other.cancelled
        self.error_messages.extend(other.error_messages)
