from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

from mypicsdb3 import metadata
from mypicsdb3.metadata import extract_metadata
from mypicsdb3.metadata_mapping import (
    MetadataMappingRule,
    effective_mapping_rules,
    metadata_index_signature,
    metadata_mapping_signature,
)


class XmpFilesystem:
    def __init__(self, data: bytes):
        self.data = data

    def read_prefix(self, _path: str, _max_bytes: int) -> bytes:
        return self.data

    def open_binary(self, _path: str):
        return io.BytesIO(b"")

    @contextlib.contextmanager
    def materialized(self, _path: str, _max_bytes: int):
        yield None


def settings(**overrides):
    values = {
        "metadata_prefix_mb": 1,
        "deep_metadata_max_mb": 64,
        "store_gps": False,
        "read_xmp": True,
        "read_iptc": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def xmp_bytes() -> bytes:
    return b'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
      <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
               xmlns:xmp="http://ns.adobe.com/xap/1.0/"
               xmlns:dc="http://purl.org/dc/elements/1.1/"
               xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
               xmlns:iptc="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
        <rdf:Description xmp:CreateDate="2020-07-17T14:15:16"
                         photoshop:City="Stockholm"
                         iptc:CountryName="Sweden">
          <dc:subject><rdf:Bag><rdf:li>Family</rdf:li></rdf:Bag></dc:subject>
        </rdf:Description>
      </rdf:RDF>
    </x:xmpmeta>'''


def test_builtin_mapping_preserves_canonical_xmp_fields(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "exifread", None)
    result = extract_metadata("picture.jpg", XmpFilesystem(xmp_bytes()), settings(), 100)

    assert result.taken_at == "2020-07-17 14:15:16"
    assert result.taken_source == "XMP"
    assert result.location["city"] == "Stockholm"
    assert result.location["country"] == "Sweden"
    assert result.keywords == ["Family"]


def test_custom_mapping_can_redirect_and_suppress_builtin_xmp_tags(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "exifread", None)
    overrides = (
        MetadataMappingRule("xmp", "photoshop:City", "sublocation", 5),
        MetadataMappingRule("xmp", "Iptc4xmpExt:CountryName", None, 5),
    )

    result = extract_metadata(
        "picture.jpg",
        XmpFilesystem(xmp_bytes()),
        settings(),
        100,
        mapping_rules=overrides,
    )

    assert "city" not in result.location
    assert result.location["sublocation"] == "Stockholm"
    assert "country" not in result.location


def test_custom_mapping_can_add_unknown_xmp_local_name(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "exifread", None)
    data = xmp_bytes().replace(b'photoshop:City="Stockholm"', b'photoshop:City="Stockholm" photoshop:LegacyPlace="Old town"')
    overrides = (MetadataMappingRule("xmp", "LegacyPlace", "city", 1),)

    result = extract_metadata(
        "picture.jpg",
        XmpFilesystem(data),
        settings(),
        100,
        mapping_rules=overrides,
    )

    assert result.location["city"] == "Old town"


def test_mapping_signature_is_deterministic_and_changes_with_override() -> None:
    default = metadata_mapping_signature(())
    same = metadata_mapping_signature([])
    changed = metadata_mapping_signature(
        [MetadataMappingRule("xmp", "CountryName", None, 10)]
    )
    assert default == same
    assert changed != default
    assert len(default) == 64


def test_metadata_index_signature_includes_extraction_settings() -> None:
    first = metadata_index_signature(settings(read_xmp=True), ())
    second = metadata_index_signature(settings(read_xmp=False), ())
    assert first != second


def test_catalog_roundtrips_mapping_overrides(tmp_path) -> None:
    from mypicsdb3.config import Settings
    from mypicsdb3.db.catalog import Catalog
    from mypicsdb3.db.engine import DatabaseEngine

    catalog = Catalog(DatabaseEngine(Settings(profile_path=str(tmp_path))))
    catalog.initialize()
    catalog.set_metadata_mapping_rule(
        MetadataMappingRule("xmp", "Iptc4xmpExt:CountryName", "country", 7)
    )
    catalog.set_metadata_mapping_rule(
        MetadataMappingRule("iptc", "caption/abstract", None, 9)
    )

    rules = catalog.list_metadata_mapping_overrides()
    assert [(rule.source_type, rule.source_tag, rule.target_field, rule.priority) for rule in rules] == [
        ("iptc", "caption/abstract", None, 9),
        ("xmp", "CountryName", "country", 7),
    ]
    assert catalog.clear_metadata_mapping_rule("xmp", "CountryName") is True
    assert catalog.clear_metadata_mapping_rules() == 1
    assert catalog.list_metadata_mapping_overrides() == []
