from __future__ import annotations

import contextlib
import io
import struct
from types import SimpleNamespace

from mypicsdb3 import metadata
from mypicsdb3.metadata import extract_metadata, image_dimensions, parse_xmp


def test_image_dimensions_for_png_gif_bmp_and_webp() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 640, 480)
    gif = b"GIF89a" + struct.pack("<HH", 320, 240)
    bmp = b"BM" + b"\x00" * 16 + struct.pack("<ii", 800, -600)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (1023).to_bytes(3, "little") + (767).to_bytes(3, "little")
    assert image_dimensions(png) == (640, 480)
    assert image_dimensions(gif) == (320, 240)
    assert image_dimensions(bmp) == (800, 600)
    assert image_dimensions(webp) == (1024, 768)


def test_parse_xmp_extracts_date_keywords_rating_location_and_caption() -> None:
    data = b'''prefix<x:xmpmeta xmlns:x="adobe:ns:meta/">
      <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
               xmlns:xmp="http://ns.adobe.com/xap/1.0/"
               xmlns:dc="http://purl.org/dc/elements/1.1/"
               xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
        <rdf:Description xmp:CreateDate="2020-07-17T14:15:16" xmp:Rating="4" photoshop:City="Stockholm">
          <dc:subject><rdf:Bag><rdf:li>Family</rdf:li><rdf:li>Summer</rdf:li></rdf:Bag></dc:subject>
          <dc:description><rdf:Alt><rdf:li>At the lake</rdf:li></rdf:Alt></dc:description>
        </rdf:Description>
      </rdf:RDF>
    </x:xmpmeta>suffix'''
    result = parse_xmp(data)
    assert result["taken_at"] == "2020-07-17 14:15:16"
    assert result["rating"] == 4
    assert result["location"]["city"] == "Stockholm"
    assert "Family" in result["keywords"]
    assert "Summer" in result["keywords"]
    assert result["caption"] == "At the lake"


class _IndexedOnlyIPTCInfo:
    def __init__(self, _path: str, force: bool = False):
        assert force is True
        self.values = {
            "keywords": [b"Family", b"Summer"],
            "city": b"Stockholm",
            "province/state": b"Stockholm County",
            "country/primary location name": b"Sweden",
            "sub-location": b"At the lake",
            "caption/abstract": b"A summer caption",
            "date created": b"2026-07-29",
        }

    def __getitem__(self, key: str):
        return self.values[key]


def test_read_iptc_does_not_require_dictionary_get(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "IPTCInfo", _IndexedOnlyIPTCInfo)

    result = metadata._read_iptc("picture.jpg")

    assert result["keywords"] == ["Family", "Summer"]
    assert result["location"] == {
        "city": "Stockholm",
        "state": "Stockholm County",
        "country": "Sweden",
        "sublocation": "At the lake",
    }
    assert result["caption"] == "A summer caption"
    assert result["date_created"] == "2026-07-29 00:00:00"


class _NonJpegFilesystem:
    def __init__(self):
        self.materialized_calls = 0

    def read_prefix(self, _path: str, _max_bytes: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 24

    def open_binary(self, _path: str):
        return io.BytesIO(b"")

    @contextlib.contextmanager
    def materialized(self, _path: str, _max_bytes: int):
        self.materialized_calls += 1
        yield "/tmp/should-not-be-used.png"


def test_extract_metadata_skips_iptc_for_non_jpeg(monkeypatch) -> None:
    filesystem = _NonJpegFilesystem()
    settings = SimpleNamespace(
        metadata_prefix_mb=1,
        deep_metadata_max_mb=64,
        store_gps=False,
        read_xmp=False,
        read_iptc=True,
    )
    monkeypatch.setattr(metadata, "exifread", None)
    monkeypatch.setattr(
        metadata,
        "IPTCInfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("IPTCInfo must not inspect non-JPEG files")
        ),
    )

    result = extract_metadata("picture.png", filesystem, settings, file_size=32)

    assert result.mime_type == "image/png"
    assert filesystem.materialized_calls == 0


class _Tag:
    def __init__(self, text, values=None):
        self.text = text
        self.values = values if values is not None else [text]

    def __str__(self):
        return str(self.text)


class _ExifReader:
    @staticmethod
    def process_file(_stream, details=False, strict=False):
        assert details is False
        assert strict is False
        return {
            "Image Make": _Tag("Samsung"),
            "Image Model": _Tag("SM-S921B"),
            "GPS GPSLatitude": _Tag("59 deg", [59, 19, 45.48]),
            "GPS GPSLatitudeRef": _Tag("N"),
            "GPS GPSLongitude": _Tag("18 deg", [18, 4, 6.96]),
            "GPS GPSLongitudeRef": _Tag("E"),
        }


class _ExifFilesystem:
    def read_prefix(self, _path, _max_bytes):
        return b"\xff\xd8\xff" + b"\x00" * 64

    def open_binary(self, _path):
        return io.BytesIO(b"test")

    @contextlib.contextmanager
    def materialized(self, _path, _max_bytes):
        yield None


def test_extract_metadata_can_report_privacy_local_extractor_diagnostics(monkeypatch) -> None:
    filesystem = _ExifFilesystem()
    settings = SimpleNamespace(
        metadata_prefix_mb=1,
        deep_metadata_max_mb=64,
        store_gps=True,
        read_xmp=False,
        read_iptc=False,
    )
    monkeypatch.setattr(metadata, "exifread", _ExifReader())
    diagnostics = {}

    result = extract_metadata(
        "picture.jpg", filesystem, settings, file_size=100, diagnostics=diagnostics
    )

    assert result.camera_make == "Samsung"
    assert result.camera_model == "SM-S921B"
    assert round(result.gps_latitude, 4) == 59.3293
    assert round(result.gps_longitude, 4) == 18.0686
    assert diagnostics["exifread_available"] is True
    assert diagnostics["exif_tag_count"] == 6
    assert diagnostics["exif_make"] == "Samsung"
    assert diagnostics["exif_model"] == "SM-S921B"
    assert diagnostics["gps_latitude_present"] is True
    assert diagnostics["gps_longitude_present"] is True
    assert diagnostics["xmp_present"] is False
    assert diagnostics["iptc_loaded"] is False


def _jpeg_with_core_exif() -> bytes:
    make = b"Samsung\x00"
    model = b"SM-S921B\x00"
    ifd0_offset = 8
    ifd0_size = 2 + (3 * 12) + 4
    make_offset = ifd0_offset + ifd0_size
    model_offset = make_offset + len(make)
    gps_offset = model_offset + len(model)
    gps_size = 2 + (4 * 12) + 4
    latitude_offset = gps_offset + gps_size
    longitude_offset = latitude_offset + 24

    tiff = bytearray(b"II*\x00" + struct.pack("<I", ifd0_offset))
    tiff += struct.pack("<H", 3)
    tiff += struct.pack("<HHI", 0x010F, 2, len(make)) + struct.pack("<I", make_offset)
    tiff += struct.pack("<HHI", 0x0110, 2, len(model)) + struct.pack("<I", model_offset)
    tiff += struct.pack("<HHI", 0x8825, 4, 1) + struct.pack("<I", gps_offset)
    tiff += struct.pack("<I", 0)
    tiff += make + model

    tiff += struct.pack("<H", 4)
    tiff += struct.pack("<HHI", 0x0001, 2, 2) + b"N\x00\x00\x00"
    tiff += struct.pack("<HHI", 0x0002, 5, 3) + struct.pack("<I", latitude_offset)
    tiff += struct.pack("<HHI", 0x0003, 2, 2) + b"E\x00\x00\x00"
    tiff += struct.pack("<HHI", 0x0004, 5, 3) + struct.pack("<I", longitude_offset)
    tiff += struct.pack("<I", 0)
    for numerator, denominator in ((59, 1), (19, 1), (4548, 100)):
        tiff += struct.pack("<II", numerator, denominator)
    for numerator, denominator in ((18, 1), (4, 1), (696, 100)):
        tiff += struct.pack("<II", numerator, denominator)

    payload = b"Exif\x00\x00" + bytes(tiff)
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"


class _BrokenUnicodeExifReader:
    @staticmethod
    def process_file(_stream, details=False, strict=False):
        assert details is False
        assert strict is False
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


class _FallbackExifFilesystem:
    def __init__(self):
        self.data = _jpeg_with_core_exif()

    def read_prefix(self, _path, _max_bytes):
        return self.data

    def open_binary(self, _path):
        return io.BytesIO(self.data)

    @contextlib.contextmanager
    def materialized(self, _path, _max_bytes):
        yield None


def test_extract_metadata_recovers_core_exif_when_exifread_unicode_decode_fails(monkeypatch) -> None:
    filesystem = _FallbackExifFilesystem()
    settings = SimpleNamespace(
        metadata_prefix_mb=1,
        deep_metadata_max_mb=64,
        store_gps=True,
        read_xmp=False,
        read_iptc=False,
    )
    monkeypatch.setattr(metadata, "exifread", _BrokenUnicodeExifReader())
    diagnostics = {}

    result = extract_metadata(
        "picture.jpg", filesystem, settings, file_size=len(filesystem.data), diagnostics=diagnostics
    )

    assert result.camera_make == "Samsung"
    assert result.camera_model == "SM-S921B"
    assert round(result.gps_latitude, 4) == 59.3293
    assert round(result.gps_longitude, 4) == 18.0686
    assert diagnostics["exif_fallback_used"] is True
    assert diagnostics["exif_fallback_tag_count"] == 6
    assert diagnostics["exif_make"] == "Samsung"
    assert diagnostics["exif_model"] == "SM-S921B"
    assert diagnostics["gps_latitude_present"] is True
    assert diagnostics["gps_longitude_present"] is True
    assert diagnostics["exif_error"].startswith("UnicodeDecodeError:")
