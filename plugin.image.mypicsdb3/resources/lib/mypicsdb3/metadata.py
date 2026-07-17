from __future__ import annotations

import mimetypes
import re
import struct
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import Settings
from .filesystem import Filesystem
from .models import MetadataResult
from .utils import decode_text, stable_json_hash, unique_strings

try:
    import exifread  # type: ignore
except ImportError:  # pragma: no cover
    exifread = None

try:
    from iptcinfo3 import IPTCInfo  # type: ignore
except ImportError:  # pragma: no cover
    IPTCInfo = None


_DATE_PATTERNS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d",
    "%Y-%m-%d",
)


def _as_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if hasattr(value, "num") and hasattr(value, "den"):
        denominator = float(value.den)
        return float(value.num) / denominator if denominator else None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None


def _tag_value(tags: Dict[str, Any], *names: str) -> Any:
    for name in names:
        tag = tags.get(name)
        if tag is None:
            continue
        if hasattr(tag, "values"):
            return tag.values
        return tag
    return None


def _tag_text(tags: Dict[str, Any], *names: str) -> str:
    for name in names:
        tag = tags.get(name)
        if tag is not None:
            text = decode_text(tag)
            if text:
                return text
    return ""


def _normalise_date(value: Any) -> Optional[str]:
    text = decode_text(value).replace("\x00", "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).replace("T", " ", 1)
    for pattern in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text[:19] if "%H" in pattern else text[:10], pattern)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    match = re.search(r"(19|20)\d{2}[-:]\d{2}[-:]\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?", text)
    if match:
        candidate = match.group(0).replace(":", "-", 2).replace("T", " ")
        if len(candidate) == 10:
            candidate += " 00:00:00"
        return candidate
    return None


def _gps_coordinate(values: Any, ref: str) -> Optional[float]:
    if values is None:
        return None
    try:
        parts = list(values)
        if len(parts) < 3:
            return None
        degrees = _as_number(parts[0])
        minutes = _as_number(parts[1])
        seconds = _as_number(parts[2])
        if degrees is None or minutes is None or seconds is None:
            return None
        result = degrees + minutes / 60.0 + seconds / 3600.0
        if ref.upper() in {"S", "W"}:
            result = -result
        return round(result, 8)
    except Exception:
        return None


def _decode_xp_keywords(value: Any) -> List[str]:
    if value is None:
        return []
    try:
        if isinstance(value, (list, tuple)):
            raw = bytes(int(item) & 0xFF for item in value)
        elif isinstance(value, bytes):
            raw = value
        else:
            raw = bytes(value)
        text = raw.decode("utf-16-le", "ignore").strip("\x00 ")
        return [item.strip() for item in re.split(r"[;,]", text) if item.strip()]
    except Exception:
        text = decode_text(value)
        return [item.strip() for item in re.split(r"[;,]", text) if item.strip()]


def _jpeg_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    if not data.startswith(b"\xff\xd8"):
        return None, None
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > length:
            break
        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > length:
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height, width = struct.unpack(">HH", data[index + 3:index + 7])
            return int(width), int(height)
        index += segment_length
    return None, None


def image_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    if len(data) >= 26 and data.startswith(b"BM"):
        width, height = struct.unpack("<ii", data[18:26])
        return abs(int(width)), abs(int(height))
    width, height = _jpeg_dimensions(data)
    if width and height:
        return width, height
    if len(data) >= 30 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X" and len(data) >= 30:
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
    return None, None


def _xmp_fragment(data: bytes) -> str:
    start_candidates = [index for index in (data.find(b"<x:xmpmeta"), data.find(b"<xmpmeta"), data.find(b"<rdf:RDF")) if index >= 0]
    if not start_candidates:
        return ""
    start = min(start_candidates)
    end_markers = (b"</x:xmpmeta>", b"</xmpmeta>", b"</rdf:RDF>")
    end = -1
    marker_length = 0
    for marker in end_markers:
        found = data.find(marker, start)
        if found >= 0 and (end < 0 or found < end):
            end = found
            marker_length = len(marker)
    if end < 0:
        return data[start:].decode("utf-8", "ignore")
    return data[start:end + marker_length].decode("utf-8", "ignore")


def _xmp_blocks(xml: str, local_name: str) -> List[str]:
    escaped = re.escape(local_name)
    pattern = rf"<(?:[\w.-]+:)?{escaped}(?:\s[^>]*)?>(.*?)</(?:[\w.-]+:)?{escaped}\s*>"
    return re.findall(pattern, xml, flags=re.DOTALL)


def _xmp_values(xml: str, local_name: str) -> List[str]:
    escaped = re.escape(local_name)
    results: List[str] = []
    for value in _xmp_blocks(xml, local_name):
        value = re.sub(r"<[^>]+>", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            results.append(value)
    attribute_pattern = rf"\b(?:[\w.-]+:)?{escaped}\s*=\s*[\"']([^\"']+)[\"']"
    results.extend(re.findall(attribute_pattern, xml, flags=re.IGNORECASE | re.DOTALL))
    return unique_strings(results)


def _xmp_list_values(xml: str, *local_names: str) -> List[str]:
    results: List[str] = []
    for local_name in local_names:
        for block in _xmp_blocks(xml, local_name):
            for value in re.findall(r"<(?:[\w.-]+:)?li(?:\s[^>]*)?>(.*?)</(?:[\w.-]+:)?li\s*>", block, re.I | re.S):
                value = re.sub(r"<[^>]+>", " ", value)
                value = re.sub(r"\s+", " ", value).strip()
                if value:
                    results.append(value)
    return unique_strings(results)


def parse_xmp(data: bytes) -> Dict[str, Any]:
    xml = _xmp_fragment(data)
    if not xml:
        return {}
    keywords = _xmp_list_values(xml, "subject", "Keywords", "HierarchicalSubject")
    rating_values = _xmp_values(xml, "Rating")
    rating = None
    if rating_values:
        try:
            rating = max(0, min(5, int(float(rating_values[0]))))
        except ValueError:
            pass
    date_values = []
    for name in ("DateTimeOriginal", "CreateDate", "DateCreated"):
        date_values.extend(_xmp_values(xml, name))
    location = {}
    for key, names in {
        "city": ("City",),
        "state": ("State", "ProvinceState"),
        "country": ("Country", "CountryName"),
        "sublocation": ("Location", "Sublocation"),
    }.items():
        for name in names:
            values = _xmp_values(xml, name)
            if values:
                location[key] = values[0]
                break
    caption_values = _xmp_values(xml, "description") or _xmp_values(xml, "Description")
    return {
        "taken_at": _normalise_date(date_values[0]) if date_values else None,
        "keywords": keywords,
        "rating": rating,
        "location": location,
        "caption": caption_values[0] if caption_values else None,
    }


def _read_iptc(path: str) -> Dict[str, Any]:
    if IPTCInfo is None:
        return {}
    try:
        info = IPTCInfo(path, force=True)
    except Exception:
        return {}
    keywords = info.get("keywords") or []
    if not isinstance(keywords, (list, tuple)):
        keywords = [keywords]
    location = {}
    for output, iptc_key in (("city", "city"), ("state", "province/state"), ("country", "country/primary location name"), ("sublocation", "sub-location")):
        value = decode_text(info.get(iptc_key))
        if value:
            location[output] = value
    return {
        "keywords": unique_strings(keywords),
        "location": location,
        "caption": decode_text(info.get("caption/abstract")) or None,
        "date_created": _normalise_date(info.get("date created")),
    }


def extract_metadata(path: str, filesystem: Filesystem, settings: Settings, file_size: int = 0) -> MetadataResult:
    result = MetadataResult(mime_type=mimetypes.guess_type(path)[0] or "image/unknown")
    prefix = b""
    try:
        prefix = filesystem.read_prefix(path, settings.metadata_prefix_mb * 1024 * 1024)
        result.width, result.height = image_dimensions(prefix)
    except Exception:
        prefix = b""

    tags: Dict[str, Any] = {}
    if exifread is not None:
        try:
            with filesystem.open_binary(path) as stream:
                tags = exifread.process_file(stream, details=False, strict=False)
        except Exception:
            tags = {}

    date_value = _tag_text(tags, "EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime")
    result.taken_at = _normalise_date(date_value)
    result.taken_source = "EXIF DateTimeOriginal" if result.taken_at else None
    result.camera_make = _tag_text(tags, "Image Make") or None
    result.camera_model = _tag_text(tags, "Image Model") or None

    orientation_value = _tag_value(tags, "Image Orientation")
    if isinstance(orientation_value, (list, tuple)) and orientation_value:
        orientation_value = orientation_value[0]
    try:
        result.orientation = int(str(orientation_value).split()[0]) if orientation_value is not None else None
    except ValueError:
        result.orientation = None

    width_value = _tag_value(tags, "EXIF ExifImageWidth", "Image ImageWidth")
    height_value = _tag_value(tags, "EXIF ExifImageLength", "Image ImageLength")
    if isinstance(width_value, (list, tuple)) and width_value:
        width_value = width_value[0]
    if isinstance(height_value, (list, tuple)) and height_value:
        height_value = height_value[0]
    try:
        result.width = int(width_value) if width_value is not None else result.width
        result.height = int(height_value) if height_value is not None else result.height
    except (TypeError, ValueError):
        pass

    rating_value = _tag_value(tags, "Image Rating")
    if isinstance(rating_value, (list, tuple)) and rating_value:
        rating_value = rating_value[0]
    try:
        result.rating = max(0, min(5, int(rating_value))) if rating_value is not None else None
    except (TypeError, ValueError):
        result.rating = None

    result.keywords.extend(_decode_xp_keywords(_tag_value(tags, "Image XPKeywords")))

    if settings.store_gps:
        lat = _tag_value(tags, "GPS GPSLatitude")
        lon = _tag_value(tags, "GPS GPSLongitude")
        lat_ref = _tag_text(tags, "GPS GPSLatitudeRef")
        lon_ref = _tag_text(tags, "GPS GPSLongitudeRef")
        result.gps_latitude = _gps_coordinate(lat, lat_ref)
        result.gps_longitude = _gps_coordinate(lon, lon_ref)

    if settings.read_xmp and prefix:
        xmp = parse_xmp(prefix)
        if not result.taken_at and xmp.get("taken_at"):
            result.taken_at = xmp["taken_at"]
            result.taken_source = "XMP"
        result.keywords.extend(xmp.get("keywords", []))
        if result.rating is None and xmp.get("rating") is not None:
            result.rating = xmp["rating"]
        result.location.update(xmp.get("location", {}))
        result.caption = xmp.get("caption") or result.caption

    if settings.read_iptc and (not file_size or file_size <= settings.deep_metadata_max_mb * 1024 * 1024):
        with filesystem.materialized(path, settings.deep_metadata_max_mb * 1024 * 1024) as local_path:
            if local_path:
                iptc = _read_iptc(local_path)
                result.keywords.extend(iptc.get("keywords", []))
                result.location.update({key: value for key, value in iptc.get("location", {}).items() if value})
                result.caption = iptc.get("caption") or result.caption
                if not result.taken_at and iptc.get("date_created"):
                    result.taken_at = iptc["date_created"]
                    result.taken_source = "IPTC"

    result.keywords = unique_strings(result.keywords)
    if not settings.store_gps:
        result.gps_latitude = None
        result.gps_longitude = None
    result.metadata_hash = stable_json_hash({
        "taken_at": result.taken_at,
        "taken_source": result.taken_source,
        "width": result.width,
        "height": result.height,
        "orientation": result.orientation,
        "mime_type": result.mime_type,
        "camera_make": result.camera_make,
        "camera_model": result.camera_model,
        "rating": result.rating,
        "gps_latitude": result.gps_latitude,
        "gps_longitude": result.gps_longitude,
        "keywords": result.keywords,
        "location": result.location,
        "caption": result.caption,
    })
    return result
