from __future__ import annotations

import html
import mimetypes
import re
import struct
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import Settings
from .filesystem import Filesystem
from .models import MetadataResult
from .metadata_mapping import (
    MetadataMappingRule,
    effective_mapping_rules,
    mapping_rules_by_source,
)
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


_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


_XMP_LOCATION_ALIASES = {
    "city": ("City", "LocationShownCity", "LocationCreatedCity"),
    "state": (
        "State",
        "ProvinceState",
        "LocationShownProvinceState",
        "LocationCreatedProvinceState",
    ),
    "country": (
        "Country",
        "CountryName",
        "LocationShownCountryName",
        "LocationCreatedCountryName",
    ),
    "sublocation": (
        "Location",
        "Sublocation",
        "SubLocation",
        "LocationShownSublocation",
        "LocationCreatedSublocation",
    ),
}
_XMP_GPS_LATITUDE_NAMES = ("GPSLatitude", "LocationShownGPSLatitude", "LocationCreatedGPSLatitude")
_XMP_GPS_LONGITUDE_NAMES = ("GPSLongitude", "LocationShownGPSLongitude", "LocationCreatedGPSLongitude")
_XMP_GPS_LATITUDE_REF_NAMES = ("GPSLatitudeRef",)
_XMP_GPS_LONGITUDE_REF_NAMES = ("GPSLongitudeRef",)


def _embedded_exif_tiff(data: bytes) -> bytes:
    """Return the TIFF payload from JPEG EXIF data or a TIFF prefix.

    This intentionally parses only the container boundary. It is used as a
    resilience fallback when ExifRead aborts on an unrelated malformed or
    incorrectly encoded tag.
    """
    if len(data) >= 8 and data[:4] in {b"II*\x00", b"MM\x00*"}:
        return data
    if not data.startswith(b"\xff\xd8"):
        return b""
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:  # Start of scan; metadata segments are before this.
            break
        if index + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > len(data):
            break
        payload = data[index + 2:index + segment_length]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            return payload[6:]
        index += segment_length
    return b""


def _tiff_scalar_or_list(values: List[Any]) -> Any:
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def _tiff_value(tiff: bytes, endian: str, entry: bytes) -> Any:
    if len(entry) != 12:
        return None
    value_type = struct.unpack(endian + "H", entry[2:4])[0]
    count = struct.unpack(endian + "I", entry[4:8])[0]
    item_size = _TIFF_TYPE_SIZES.get(value_type)
    if not item_size or count > 1000000:
        return None
    byte_count = item_size * count
    if byte_count <= 4:
        raw = entry[8:8 + byte_count]
    else:
        offset = struct.unpack(endian + "I", entry[8:12])[0]
        if offset < 0 or offset + byte_count > len(tiff):
            return None
        raw = tiff[offset:offset + byte_count]
    if value_type == 2:  # ASCII. EXIF ASCII is byte-oriented, not guaranteed UTF-8.
        return raw.split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
    if value_type in {1, 7}:
        return raw if value_type == 7 else _tiff_scalar_or_list(list(raw))
    if value_type == 3:
        return _tiff_scalar_or_list(list(struct.unpack(endian + ("H" * count), raw)))
    if value_type == 4:
        return _tiff_scalar_or_list(list(struct.unpack(endian + ("I" * count), raw)))
    if value_type == 9:
        return _tiff_scalar_or_list(list(struct.unpack(endian + ("i" * count), raw)))
    if value_type in {5, 10}:
        fmt = "I" if value_type == 5 else "i"
        values = []
        for index in range(count):
            start = index * 8
            numerator, denominator = struct.unpack(endian + fmt + fmt, raw[start:start + 8])
            values.append(float(numerator) / float(denominator) if denominator else 0.0)
        return _tiff_scalar_or_list(values)
    return None


def _tiff_ifd(tiff: bytes, endian: str, offset: Any) -> Dict[int, Any]:
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return {}
    if offset < 0 or offset + 2 > len(tiff):
        return {}
    count = struct.unpack(endian + "H", tiff[offset:offset + 2])[0]
    if count > 4096:
        return {}
    result: Dict[int, Any] = {}
    cursor = offset + 2
    for _index in range(count):
        entry = tiff[cursor:cursor + 12]
        if len(entry) < 12:
            break
        tag_id = struct.unpack(endian + "H", entry[:2])[0]
        value = _tiff_value(tiff, endian, entry)
        if value is not None:
            result[tag_id] = value
        cursor += 12
    return result


def _fallback_exif_tags(data: bytes) -> Dict[str, Any]:
    """Recover critical EXIF fields without decoding free-form text tags.

    ExifRead 2.x and newer can abort the complete file when a malformed Unicode
    UserComment is encountered. This tiny TIFF reader deliberately ignores
    UserComment/MakerNote and recovers only the stable fields MyPicsDB needs for
    catalogue browsing and GPS.
    """
    tiff = _embedded_exif_tiff(data)
    if len(tiff) < 8 or tiff[:2] not in {b"II", b"MM"}:
        return {}
    endian = "<" if tiff[:2] == b"II" else ">"
    expected_magic = struct.unpack(endian + "H", tiff[2:4])[0]
    if expected_magic != 42:
        return {}
    ifd0_offset = struct.unpack(endian + "I", tiff[4:8])[0]
    ifd0 = _tiff_ifd(tiff, endian, ifd0_offset)
    tags: Dict[str, Any] = {}
    for tag_id, name in (
        (0x010F, "Image Make"),
        (0x0110, "Image Model"),
        (0x0112, "Image Orientation"),
        (0x0132, "Image DateTime"),
        (0x4746, "Image Rating"),
        (0x9C9E, "Image XPKeywords"),
    ):
        if tag_id in ifd0:
            tags[name] = ifd0[tag_id]

    exif_ifd = _tiff_ifd(tiff, endian, ifd0.get(0x8769))
    for tag_id, name in (
        (0x9003, "EXIF DateTimeOriginal"),
        (0x9004, "EXIF DateTimeDigitized"),
        (0xA002, "EXIF ExifImageWidth"),
        (0xA003, "EXIF ExifImageLength"),
    ):
        if tag_id in exif_ifd:
            tags[name] = exif_ifd[tag_id]

    gps_ifd = _tiff_ifd(tiff, endian, ifd0.get(0x8825))
    for tag_id, name in (
        (0x0001, "GPS GPSLatitudeRef"),
        (0x0002, "GPS GPSLatitude"),
        (0x0003, "GPS GPSLongitudeRef"),
        (0x0004, "GPS GPSLongitude"),
    ):
        if tag_id in gps_ifd:
            tags[name] = gps_ifd[tag_id]
    return tags


def _fallback_exif_tags_from_stream(stream, max_scan_bytes: int) -> Dict[str, Any]:
    """Locate JPEG EXIF without decoding unrelated APP/text payloads.

    The normal fallback works from the configured metadata prefix. Some JPEGs
    contain large APP segments before EXIF, and a prefix can also be unavailable
    even though a fresh VFS stream is readable. This marker walker skips segment
    payloads with ``seek`` and reads only EXIF APP1 data. It is used only after
    the primary ExifRead path has already failed.
    """

    try:
        limit = max(64 * 1024, int(max_scan_bytes or 0))
        stream.seek(0, 0)
        if stream.read(2) != b"\xff\xd8":
            return {}
        scanned = 2
        while scanned + 4 <= limit:
            marker_prefix = stream.read(1)
            scanned += 1
            if not marker_prefix:
                break
            if marker_prefix != b"\xff":
                continue
            marker_byte = stream.read(1)
            scanned += 1
            while marker_byte == b"\xff":
                marker_byte = stream.read(1)
                scanned += 1
            if not marker_byte:
                break
            marker = marker_byte[0]
            if marker in {0xD8, 0xD9}:
                continue
            if marker == 0xDA:
                break
            length_bytes = stream.read(2)
            scanned += 2
            if len(length_bytes) != 2:
                break
            segment_length = struct.unpack(">H", length_bytes)[0]
            if segment_length < 2:
                break
            payload_length = segment_length - 2
            if scanned + payload_length > limit:
                break
            if marker == 0xE1:
                payload = stream.read(payload_length)
                scanned += len(payload)
                if len(payload) != payload_length:
                    break
                if payload.startswith(b"Exif\x00\x00"):
                    wrapped = (
                        b"\xff\xd8\xff\xe1"
                        + struct.pack(">H", segment_length)
                        + payload
                        + b"\xff\xd9"
                    )
                    return _fallback_exif_tags(wrapped)
                continue
            stream.seek(payload_length, 1)
            scanned += payload_length
    except Exception:
        return {}
    return {}


def _jpeg_metadata_prefix_from_stream(stream, max_scan_bytes: int) -> bytes:
    """Read only JPEG header segments needed for metadata extraction.

    JPEG EXIF/XMP and SOF dimension markers live before Start Of Scan.  Walking
    marker headers and seeking over unrelated APP payloads avoids transferring
    several megabytes of compressed image data from SMB merely to obtain the
    metadata prefix.  The logical scan remains bounded by the configured prefix
    limit and returns a synthetic, valid-enough JPEG header for the existing
    EXIF/XMP/dimension helpers.
    """
    limit = max(64 * 1024, int(max_scan_bytes or 0))
    stream.seek(0, 0)
    if stream.read(2) != b"\xff\xd8":
        return b""
    buffered = bytearray(b"\xff\xd8")
    scanned = 2
    while scanned + 4 <= limit:
        prefix = stream.read(1)
        scanned += 1
        if not prefix:
            break
        if prefix != b"\xff":
            continue
        marker_byte = stream.read(1)
        scanned += 1
        while marker_byte == b"\xff":
            marker_byte = stream.read(1)
            scanned += 1
        if not marker_byte:
            break
        marker = marker_byte[0]
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        length_bytes = stream.read(2)
        scanned += 2
        if len(length_bytes) != 2:
            break
        segment_length = struct.unpack(">H", length_bytes)[0]
        if segment_length < 2:
            break
        payload_length = segment_length - 2
        if scanned + payload_length > limit:
            break

        # Keep APP1 (EXIF/XMP) and SOF segments.  Everything else can be
        # skipped without transferring its payload over VFS/SMB.
        keep = marker == 0xE1 or marker in {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        if keep:
            payload = stream.read(payload_length)
            scanned += len(payload)
            if len(payload) != payload_length:
                break
            buffered.extend(b"\xff" + bytes((marker,)) + length_bytes + payload)
        else:
            stream.seek(payload_length, 1)
            scanned += payload_length
    buffered.extend(b"\xff\xd9")
    return bytes(buffered)


def _metadata_prefix(path: str, filesystem: Filesystem, max_bytes: int) -> bytes:
    """Return a bounded metadata prefix with a JPEG-specific low-I/O path."""
    with filesystem.open_binary(path) as stream:
        magic = stream.read(3)
        stream.seek(0, 0)
        if magic.startswith(b"\xff\xd8\xff"):
            return _jpeg_metadata_prefix_from_stream(stream, max_bytes)
    # Preserve Filesystem.read_prefix overrides for non-JPEG formats and test
    # adapters; only JPEG takes the marker-aware path above.
    return filesystem.read_prefix(path, max_bytes)


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
        value = html.unescape(re.sub(r"\s+", " ", value).strip())
        if value:
            results.append(value)
    attribute_pattern = rf"\b(?:[\w.-]+:)?{escaped}\s*=\s*[\"']([^\"']+)[\"']"
    results.extend(
        html.unescape(value)
        for value in re.findall(attribute_pattern, xml, flags=re.IGNORECASE | re.DOTALL)
    )
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


def _xmp_first_value(xml: str, names: Iterable[str]) -> Tuple[str, str]:
    for name in names:
        values = _xmp_values(xml, name)
        if values:
            return name, values[0]
    return "", ""


def _xmp_coordinate(value: Any, ref: str, maximum: float) -> Optional[float]:
    """Parse common XMP GPS encodings (decimal, deg/min, or DMS)."""
    text = html.unescape(decode_text(value)).strip()
    if not text:
        return None
    direction = (str(ref or "").strip().upper()[:1] or "")
    suffix = re.search(r"([NSEW])\s*$", text, flags=re.IGNORECASE)
    if suffix:
        direction = suffix.group(1).upper()
        text = text[:suffix.start()].strip()
    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", text.replace("\u2212", "-"))
    if not numbers:
        return None
    try:
        parts = [float(item) for item in numbers[:3]]
    except ValueError:
        return None
    sign = -1.0 if parts[0] < 0 else 1.0
    degrees = abs(parts[0])
    if len(parts) >= 2:
        degrees += abs(parts[1]) / 60.0
    if len(parts) >= 3:
        degrees += abs(parts[2]) / 3600.0
    if direction in {"S", "W"}:
        sign = -1.0
    elif direction in {"N", "E"}:
        sign = 1.0
    coordinate = sign * degrees
    if abs(coordinate) > float(maximum):
        return None
    return round(coordinate, 8)


def _xmp_location_data(xml: str) -> Dict[str, Any]:
    if not xml:
        return {
            "location": {},
            "location_sources": {},
            "gps_latitude": None,
            "gps_longitude": None,
            "matched": {},
        }
    location: Dict[str, str] = {}
    location_sources: Dict[str, str] = {}
    matched: Dict[str, str] = {}
    for field, aliases in _XMP_LOCATION_ALIASES.items():
        source_name, value = _xmp_first_value(xml, aliases)
        if value:
            location[field] = value
            location_sources[field] = source_name
            matched[source_name] = value

    lat_name, lat_raw = _xmp_first_value(xml, _XMP_GPS_LATITUDE_NAMES)
    lon_name, lon_raw = _xmp_first_value(xml, _XMP_GPS_LONGITUDE_NAMES)
    lat_ref_name, lat_ref = _xmp_first_value(xml, _XMP_GPS_LATITUDE_REF_NAMES)
    lon_ref_name, lon_ref = _xmp_first_value(xml, _XMP_GPS_LONGITUDE_REF_NAMES)
    for name, value in (
        (lat_name, lat_raw),
        (lon_name, lon_raw),
        (lat_ref_name, lat_ref),
        (lon_ref_name, lon_ref),
    ):
        if name and value:
            matched[name] = value
    return {
        "location": location,
        "location_sources": location_sources,
        "gps_latitude": _xmp_coordinate(lat_raw, lat_ref, 90.0) if lat_raw else None,
        "gps_longitude": _xmp_coordinate(lon_raw, lon_ref, 180.0) if lon_raw else None,
        "matched": matched,
        "gps_latitude_raw": lat_raw,
        "gps_longitude_raw": lon_raw,
    }


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
    xmp_location = _xmp_location_data(xml)
    location = dict(xmp_location["location"])
    caption_values = _xmp_values(xml, "description") or _xmp_values(xml, "Description")
    return {
        "taken_at": _normalise_date(date_values[0]) if date_values else None,
        "keywords": keywords,
        "rating": rating,
        "location": location,
        "gps_latitude": xmp_location.get("gps_latitude"),
        "gps_longitude": xmp_location.get("gps_longitude"),
        "location_fields": dict(xmp_location.get("matched") or {}),
        "caption": caption_values[0] if caption_values else None,
    }


def _is_jpeg_metadata_candidate(path: str, mime_type: str, prefix: bytes) -> bool:
    """Return whether IPTCInfo3 should inspect this picture.

    Prefer the file signature when a prefix was read successfully. Fall back to
    the MIME type or filename only when the prefix could not be read, so normal
    PNG, HEIC and other non-JPEG files never reach IPTCInfo3's blind scanner.
    """
    if prefix:
        return prefix.startswith(b"\xff\xd8\xff")
    if str(mime_type or "").strip().casefold() in {"image/jpeg", "image/pjpeg"}:
        return True
    clean_path = str(path or "").split("?", 1)[0].split("#", 1)[0].casefold()
    return clean_path.endswith((".jpg", ".jpeg", ".jpe"))


def _iptc_value(info: Any, key: str) -> Any:
    """Read one IPTCInfo3 field without assuming dictionary ``get`` support."""
    try:
        return info[key]
    except Exception:
        return None


def _read_iptc(path: str) -> Dict[str, Any]:
    if IPTCInfo is None:
        return {}
    try:
        info = IPTCInfo(path, force=True)
    except Exception:
        return {}
    keywords = _iptc_value(info, "keywords") or []
    if not isinstance(keywords, (list, tuple)):
        keywords = [keywords]
    location = {}
    for output, iptc_key in (("city", "city"), ("state", "province/state"), ("country", "country/primary location name"), ("sublocation", "sub-location")):
        value = decode_text(_iptc_value(info, iptc_key))
        if value:
            location[output] = value
    return {
        "keywords": unique_strings(keywords),
        "location": location,
        "caption": decode_text(_iptc_value(info, "caption/abstract")) or None,
        "date_created": _normalise_date(_iptc_value(info, "date created")),
    }


def _keyword_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items: List[str] = []
        for item in value:
            text = decode_text(item).strip()
            if text:
                items.append(text)
        return unique_strings(items)
    text = decode_text(value).strip()
    return unique_strings(
        item.strip() for item in re.split(r"[;,]", text) if item.strip()
    )


def _mapped_raw_values(
    source_type: str,
    source_tag: str,
    exif_tags: Dict[str, Any],
    xmp_xml: str,
    iptc_info: Any,
    target_field: str,
) -> List[Any]:
    if source_type == "exif":
        raw = _tag_value(exif_tags, source_tag)
        if target_field == "keywords" and source_tag.casefold() == "image xpkeywords":
            return list(_decode_xp_keywords(raw))
        if isinstance(raw, (list, tuple)) and target_field != "keywords":
            return [raw[0]] if raw else []
        return list(raw) if isinstance(raw, (list, tuple)) else ([raw] if raw is not None else [])
    if source_type == "xmp":
        if not xmp_xml:
            return []
        if target_field == "keywords":
            listed = _xmp_list_values(xmp_xml, source_tag)
            if listed:
                return list(listed)
        return list(_xmp_values(xmp_xml, source_tag))
    if source_type == "iptc" and iptc_info is not None:
        raw = _iptc_value(iptc_info, source_tag)
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return [raw] if raw is not None else []
    return []


def _coerce_mapped_value(target_field: str, value: Any) -> Any:
    if target_field == "taken_at":
        return _normalise_date(value)
    if target_field == "rating":
        try:
            return max(0, min(5, int(float(decode_text(value).strip()))))
        except (TypeError, ValueError):
            return None
    if target_field == "keywords":
        return _keyword_values(value)
    text = decode_text(value).replace("\x00", "").strip()
    return text or None


def _apply_mapping_rules(
    result: MetadataResult,
    rules: Iterable[MetadataMappingRule],
    exif_tags: Dict[str, Any],
    xmp_xml: str,
    iptc_info: Any,
) -> None:
    scalar_values: Dict[str, Tuple[int, str, str, Any]] = {}
    keywords: List[str] = []
    for rule in rules:
        if rule.target_field is None:
            continue
        raw_values = _mapped_raw_values(
            rule.source_type,
            rule.source_tag,
            exif_tags,
            xmp_xml,
            iptc_info,
            rule.target_field,
        )
        if not raw_values:
            continue
        if rule.target_field == "keywords":
            for raw in raw_values:
                coerced = _coerce_mapped_value("keywords", raw)
                if coerced:
                    keywords.extend(coerced)
            continue
        for raw in raw_values:
            coerced = _coerce_mapped_value(rule.target_field, raw)
            if coerced is None or coerced == "":
                continue
            current = scalar_values.get(rule.target_field)
            candidate = (int(rule.priority), rule.source_type, rule.source_tag, coerced)
            if current is None or candidate[0] < current[0]:
                scalar_values[rule.target_field] = candidate
            break

    if "taken_at" in scalar_values:
        _priority, source_type, source_tag, value = scalar_values["taken_at"]
        result.taken_at = value
        result.taken_source = source_tag if source_type == "exif" else source_type.upper()
    for field_name in ("camera_make", "camera_model", "rating", "caption"):
        if field_name in scalar_values:
            setattr(result, field_name, scalar_values[field_name][3])
    for field_name in ("country", "state", "city", "sublocation"):
        if field_name in scalar_values:
            result.location[field_name] = scalar_values[field_name][3]
    result.keywords = unique_strings(keywords)


def extract_metadata(
    path: str,
    filesystem: Filesystem,
    settings: Settings,
    file_size: int = 0,
    mapping_rules: Optional[Iterable[MetadataMappingRule]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> MetadataResult:
    result = MetadataResult(mime_type=mimetypes.guess_type(path)[0] or "image/unknown")
    prefix = b""
    prefix_error = ""
    dimension_error = ""
    try:
        prefix = _metadata_prefix(path, filesystem, settings.metadata_prefix_mb * 1024 * 1024)
    except Exception as exc:
        prefix_error = "%s: %s" % (exc.__class__.__name__, str(exc))
        prefix = b""
    try:
        result.width, result.height = image_dimensions(prefix)
    except Exception as exc:
        # Keep a successfully read prefix even when dimension probing fails.
        # The same bytes may still contain a perfectly valid EXIF APP1 block,
        # which is especially important when ExifRead later aborts on an
        # unrelated malformed text tag.
        dimension_error = "%s: %s" % (exc.__class__.__name__, str(exc))

    tags: Dict[str, Any] = {}
    exif_error = ""
    exif_fallback_used = False
    exif_fallback_tag_count = 0
    if exifread is not None:
        try:
            with filesystem.open_binary(path) as stream:
                tags = exifread.process_file(stream, details=False, strict=False)
        except Exception as exc:
            exif_error = "%s: %s" % (exc.__class__.__name__, str(exc))
            tags = _fallback_exif_tags(prefix)
            # A failed/empty prefix must not disable the recovery path. Re-read
            # a bounded prefix from a fresh VFS handle before giving up. This is
            # still local, serial and bounded by the configured metadata prefix.
            if not tags:
                try:
                    retry_prefix = _metadata_prefix(
                        path, filesystem, settings.metadata_prefix_mb * 1024 * 1024
                    )
                except Exception:
                    retry_prefix = b""
                if retry_prefix and retry_prefix != prefix:
                    tags = _fallback_exif_tags(retry_prefix)
                    if not prefix:
                        prefix = retry_prefix
            if not tags:
                try:
                    with filesystem.open_binary(path) as fallback_stream:
                        tags = _fallback_exif_tags_from_stream(
                            fallback_stream,
                            max(
                                settings.metadata_prefix_mb * 1024 * 1024,
                                min(
                                    max(0, int(file_size or 0)),
                                    settings.deep_metadata_max_mb * 1024 * 1024,
                                ),
                            ),
                        )
                except Exception:
                    tags = {}
            exif_fallback_used = bool(tags)
            exif_fallback_tag_count = len(tags)
    elif prefix:
        tags = _fallback_exif_tags(prefix)
        exif_fallback_used = bool(tags)
        exif_fallback_tag_count = len(tags)

    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update({
            "exifread_available": exifread is not None,
            "exif_error": exif_error,
            "prefix_bytes_read": len(prefix),
            "prefix_error": prefix_error,
            "dimension_error": dimension_error,
            "embedded_exif_found": bool(_embedded_exif_tiff(prefix)),
            "exif_fallback_used": exif_fallback_used,
            "exif_fallback_tag_count": exif_fallback_tag_count,
            "exif_tag_count": len(tags),
            "exif_make": _tag_text(tags, "Image Make"),
            "exif_model": _tag_text(tags, "Image Model"),
            "gps_latitude_present": _tag_value(tags, "GPS GPSLatitude") is not None,
            "gps_longitude_present": _tag_value(tags, "GPS GPSLongitude") is not None,
            "gps_latitude_ref": _tag_text(tags, "GPS GPSLatitudeRef"),
            "gps_longitude_ref": _tag_text(tags, "GPS GPSLongitudeRef"),
        })

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

    if settings.store_gps:
        lat = _tag_value(tags, "GPS GPSLatitude")
        lon = _tag_value(tags, "GPS GPSLongitude")
        lat_ref = _tag_text(tags, "GPS GPSLatitudeRef")
        lon_ref = _tag_text(tags, "GPS GPSLongitudeRef")
        result.gps_latitude = _gps_coordinate(lat, lat_ref)
        result.gps_longitude = _gps_coordinate(lon, lon_ref)

    effective_rules = effective_mapping_rules(mapping_rules or ())
    grouped_rules = mapping_rules_by_source(effective_rules)
    xmp_xml = _xmp_fragment(prefix) if settings.read_xmp and prefix else ""
    xmp_location = _xmp_location_data(xmp_xml) if xmp_xml else {
        "location": {},
        "location_sources": {},
        "gps_latitude": None,
        "gps_longitude": None,
        "matched": {},
        "gps_latitude_raw": "",
        "gps_longitude_raw": "",
    }
    if diagnostics is not None:
        diagnostics.update({
            "xmp_enabled": bool(settings.read_xmp),
            "xmp_present": bool(xmp_xml),
            "xmp_location_fields": dict(xmp_location.get("matched") or {}),
            "xmp_gps_latitude_raw": xmp_location.get("gps_latitude_raw") or "",
            "xmp_gps_longitude_raw": xmp_location.get("gps_longitude_raw") or "",
            "xmp_gps_latitude_parsed": xmp_location.get("gps_latitude"),
            "xmp_gps_longitude_parsed": xmp_location.get("gps_longitude"),
            "iptc_enabled": bool(settings.read_iptc),
            "iptc_available": IPTCInfo is not None,
        })

    iptc_info = None
    if (
        settings.read_iptc
        and grouped_rules.get("iptc")
        and _is_jpeg_metadata_candidate(path, result.mime_type, prefix)
        and (not file_size or file_size <= settings.deep_metadata_max_mb * 1024 * 1024)
        and IPTCInfo is not None
    ):
        with filesystem.materialized(path, settings.deep_metadata_max_mb * 1024 * 1024) as local_path:
            if local_path:
                try:
                    iptc_info = IPTCInfo(local_path, force=True)
                except Exception:
                    iptc_info = None

    if diagnostics is not None:
        diagnostics["iptc_loaded"] = iptc_info is not None

    usable_rules = tuple(grouped_rules.get("exif", ()))
    if settings.read_xmp:
        usable_rules += tuple(grouped_rules.get("xmp", ()))
    if settings.read_iptc:
        usable_rules += tuple(grouped_rules.get("iptc", ()))
    usable_rules = tuple(sorted(usable_rules, key=lambda rule: (rule.priority, rule.source_type, rule.source_tag.casefold())))
    _apply_mapping_rules(result, usable_rules, tags, xmp_xml, iptc_info)

    # Preserve built-in/custom mapping precedence while accepting only the
    # additional IPTC-extension aliases introduced in 0.8.27. Legacy aliases
    # such as City/CountryName already flow through metadata_mapping.py and must
    # remain suppressible/redirectable by user overrides.
    override_xmp_tags = {
        str(rule.source_tag or "").rsplit(":", 1)[-1].strip().casefold()
        for rule in (mapping_rules or ())
        if str(rule.source_type or "").strip().casefold() == "xmp"
    }
    legacy_mapped_aliases = {
        "city", "state", "provincestate", "country", "countryname",
        "location", "sublocation",
    }
    location_sources = xmp_location.get("location_sources") or {}
    for field_name, value in (xmp_location.get("location") or {}).items():
        source_name = str(location_sources.get(field_name) or "").strip()
        local_name = source_name.rsplit(":", 1)[-1].casefold()
        if local_name in legacy_mapped_aliases or local_name in override_xmp_tags:
            continue
        if value and not result.location.get(field_name):
            result.location[field_name] = value
    if settings.store_gps:
        if result.gps_latitude is None:
            result.gps_latitude = xmp_location.get("gps_latitude")
        if result.gps_longitude is None:
            result.gps_longitude = xmp_location.get("gps_longitude")

    if diagnostics is not None:
        diagnostics["store_gps"] = bool(settings.store_gps)
        if result.gps_latitude is not None and result.gps_longitude is not None:
            if (
                _tag_value(tags, "GPS GPSLatitude") is not None
                and _tag_value(tags, "GPS GPSLongitude") is not None
            ):
                diagnostics["gps_source"] = "EXIF"
            elif xmp_location.get("gps_latitude") is not None and xmp_location.get("gps_longitude") is not None:
                diagnostics["gps_source"] = "XMP"
            else:
                diagnostics["gps_source"] = "mixed"
        else:
            diagnostics["gps_source"] = ""

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
