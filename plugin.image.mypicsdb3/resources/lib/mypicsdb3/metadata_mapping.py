from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .utils import stable_json_hash


MAPPING_VERSION = 1
# Bump whenever code-level extraction semantics change in a way that can alter
# normalized picture metadata without any corresponding settings/mapping change.
# This deliberately invalidates metadata_index_hash for unchanged source files.
METADATA_EXTRACTOR_REVISION = 1
SOURCE_TYPES = ("exif", "xmp", "iptc")
TARGET_FIELDS = (
    "taken_at",
    "camera_make",
    "camera_model",
    "rating",
    "keywords",
    "caption",
    "country",
    "state",
    "city",
    "sublocation",
)
MULTIVALUE_FIELDS = frozenset({"keywords"})


@dataclass(frozen=True)
class MetadataMappingRule:
    source_type: str
    source_tag: str
    target_field: Optional[str]
    priority: int = 100


def normalize_source_type(value: Any) -> str:
    source_type = str(value or "").strip().casefold()
    if source_type not in SOURCE_TYPES:
        raise ValueError("Unsupported metadata source type: %s" % source_type)
    return source_type


def normalize_source_tag(source_type: Any, value: Any) -> str:
    source_type = normalize_source_type(source_type)
    source_tag = " ".join(str(value or "").strip().split())
    if source_type == "xmp" and ":" in source_tag:
        # XMP prefixes are aliases chosen by the producer. MyPicsDB 3 maps the
        # local name so a rule still works when a file uses a different prefix
        # for the same property.
        source_tag = source_tag.rsplit(":", 1)[1].strip()
    if not source_tag:
        raise ValueError("Metadata source tag cannot be empty")
    if len(source_tag) > 191:
        raise ValueError("Metadata source tag is too long")
    return source_tag


def normalize_target_field(value: Any) -> Optional[str]:
    if value is None:
        return None
    target = str(value or "").strip().casefold()
    if not target or target == "ignore":
        return None
    if target not in TARGET_FIELDS:
        raise ValueError("Unsupported metadata target field: %s" % target)
    return target


def normalize_mapping_rule(rule: MetadataMappingRule) -> MetadataMappingRule:
    source_type = normalize_source_type(rule.source_type)
    source_tag = normalize_source_tag(source_type, rule.source_tag)
    target_field = normalize_target_field(rule.target_field)
    try:
        priority = int(rule.priority)
    except (TypeError, ValueError) as exc:
        raise ValueError("Metadata mapping priority must be an integer") from exc
    if priority < 0 or priority > 10000:
        raise ValueError("Metadata mapping priority must be between 0 and 10000")
    return MetadataMappingRule(source_type, source_tag, target_field, priority)


def mapping_rule_key(rule: MetadataMappingRule) -> Tuple[str, str]:
    normalized = normalize_mapping_rule(rule)
    return normalized.source_type, normalized.source_tag.casefold()


def _rule(source_type: str, source_tag: str, target_field: str, priority: int) -> MetadataMappingRule:
    return MetadataMappingRule(source_type, source_tag, target_field, priority)


# These defaults intentionally reproduce the 0.8.11 extraction precedence.
# Scalar fields use the lowest priority that yields a value. Keywords combine
# all mapped values in priority order.
BUILTIN_MAPPING_RULES: Tuple[MetadataMappingRule, ...] = (
    _rule("exif", "EXIF DateTimeOriginal", "taken_at", 10),
    _rule("exif", "EXIF DateTimeDigitized", "taken_at", 20),
    _rule("exif", "Image DateTime", "taken_at", 30),
    _rule("xmp", "DateTimeOriginal", "taken_at", 40),
    _rule("xmp", "CreateDate", "taken_at", 50),
    _rule("xmp", "DateCreated", "taken_at", 60),
    _rule("iptc", "date created", "taken_at", 70),
    _rule("exif", "Image Make", "camera_make", 10),
    _rule("exif", "Image Model", "camera_model", 10),
    _rule("exif", "Image Rating", "rating", 10),
    _rule("xmp", "Rating", "rating", 20),
    _rule("exif", "Image XPKeywords", "keywords", 10),
    _rule("xmp", "subject", "keywords", 20),
    _rule("xmp", "Keywords", "keywords", 21),
    _rule("xmp", "HierarchicalSubject", "keywords", 22),
    _rule("iptc", "keywords", "keywords", 30),
    # 0.8.11 read XMP first and then overlaid non-empty IPTC location/caption
    # values, so IPTC receives the stronger (lower) priority here.
    _rule("iptc", "country/primary location name", "country", 10),
    _rule("xmp", "Country", "country", 20),
    _rule("xmp", "CountryName", "country", 21),
    _rule("iptc", "province/state", "state", 10),
    _rule("xmp", "State", "state", 20),
    _rule("xmp", "ProvinceState", "state", 21),
    _rule("iptc", "city", "city", 10),
    _rule("xmp", "City", "city", 20),
    _rule("iptc", "sub-location", "sublocation", 10),
    _rule("xmp", "Location", "sublocation", 20),
    _rule("xmp", "Sublocation", "sublocation", 21),
    _rule("iptc", "caption/abstract", "caption", 10),
    _rule("xmp", "description", "caption", 20),
    _rule("xmp", "Description", "caption", 21),
)


def effective_mapping_rules(
    overrides: Iterable[MetadataMappingRule] = (),
) -> Tuple[MetadataMappingRule, ...]:
    by_key: Dict[Tuple[str, str], MetadataMappingRule] = {
        mapping_rule_key(rule): normalize_mapping_rule(rule)
        for rule in BUILTIN_MAPPING_RULES
    }
    for raw_rule in overrides:
        rule = normalize_mapping_rule(raw_rule)
        key = mapping_rule_key(rule)
        if rule.target_field is None:
            by_key.pop(key, None)
        else:
            by_key[key] = rule
    return tuple(
        sorted(
            by_key.values(),
            key=lambda item: (
                int(item.priority),
                item.target_field or "",
                item.source_type,
                item.source_tag.casefold(),
            ),
        )
    )


def metadata_mapping_signature(
    overrides: Iterable[MetadataMappingRule] = (),
) -> str:
    rules = effective_mapping_rules(overrides)
    return stable_json_hash(
        {
            "version": MAPPING_VERSION,
            "rules": [
                {
                    "source_type": rule.source_type,
                    "source_tag": rule.source_tag,
                    "target_field": rule.target_field,
                    "priority": int(rule.priority),
                }
                for rule in rules
            ],
        }
    )


def mapping_rules_by_source(
    rules: Sequence[MetadataMappingRule],
) -> Dict[str, Tuple[MetadataMappingRule, ...]]:
    grouped = {source_type: [] for source_type in SOURCE_TYPES}
    for raw_rule in rules:
        rule = normalize_mapping_rule(raw_rule)
        if rule.target_field is not None:
            grouped[rule.source_type].append(rule)
    return {
        source_type: tuple(sorted(values, key=lambda item: (item.priority, item.source_tag.casefold())))
        for source_type, values in grouped.items()
    }


def metadata_index_signature(settings, overrides: Iterable[MetadataMappingRule] = ()) -> str:
    """Hash every input that changes normalized picture metadata.

    Stored per picture so an unchanged file is still re-read when mapping or
    extraction settings change. The same value participates in checkpoint
    compatibility.
    """
    return stable_json_hash(
        {
            "extractor_revision": METADATA_EXTRACTOR_REVISION,
            "mapping": metadata_mapping_signature(overrides),
            "settings": {
                "read_xmp": bool(settings.read_xmp),
                "read_iptc": bool(settings.read_iptc),
                "store_gps": bool(settings.store_gps),
                "metadata_prefix_mb": int(settings.metadata_prefix_mb),
                "deep_metadata_max_mb": int(settings.deep_metadata_max_mb),
            },
        }
    )
