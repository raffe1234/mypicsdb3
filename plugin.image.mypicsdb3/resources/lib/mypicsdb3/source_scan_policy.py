from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from .utils import split_csv, split_pipe


@dataclass(frozen=True)
class SourceScanPolicy:
    """Complete scan policy for one picture source.

    The database stores only explicit per-source overrides. Sources without a
    policy row inherit the current scanner's global Kodi settings. Keeping the
    effective policy as a complete immutable value makes scanner and checkpoint
    behavior deterministic once a scan starts.
    """

    recursive: bool
    include_videos: bool
    picture_extensions: Tuple[str, ...]
    video_extensions: Tuple[str, ...]
    exclude_fragments: Tuple[str, ...]
    exclude_hidden: bool


def _normalize_extensions(values: Iterable[Any]) -> Tuple[str, ...]:
    return split_csv(",".join(str(value or "") for value in values))


def _normalize_fragments(values: Iterable[Any]) -> Tuple[str, ...]:
    return split_pipe("|".join(str(value or "") for value in values))


def normalize_source_scan_policy(policy: SourceScanPolicy) -> SourceScanPolicy:
    pictures = _normalize_extensions(policy.picture_extensions)
    videos = _normalize_extensions(policy.video_extensions)
    if not pictures:
        raise ValueError("A source scan policy must include at least one picture extension")
    if policy.include_videos and not videos:
        raise ValueError("A source scan policy that includes videos must include video extensions")
    return SourceScanPolicy(
        recursive=bool(policy.recursive),
        include_videos=bool(policy.include_videos),
        picture_extensions=pictures,
        video_extensions=videos,
        exclude_fragments=_normalize_fragments(policy.exclude_fragments),
        exclude_hidden=bool(policy.exclude_hidden),
    )


def source_scan_policy_from_settings(settings) -> SourceScanPolicy:
    """Resolve the current client-local global scanner defaults."""
    return normalize_source_scan_policy(
        SourceScanPolicy(
            recursive=True,
            include_videos=bool(settings.include_videos),
            picture_extensions=tuple(settings.extensions),
            video_extensions=tuple(settings.video_extensions),
            exclude_fragments=tuple(settings.exclude_fragments),
            exclude_hidden=bool(settings.exclude_hidden),
        )
    )


def encode_policy_list(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def decode_policy_list(value: Any) -> Tuple[str, ...]:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Stored source scan policy list is invalid") from exc
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("Stored source scan policy list is invalid")
    return tuple(decoded)


def source_scan_policy_signature_payload(policy: SourceScanPolicy) -> dict:
    policy = normalize_source_scan_policy(policy)
    return {
        "recursive": bool(policy.recursive),
        "include_videos": bool(policy.include_videos),
        "picture_extensions": list(policy.picture_extensions),
        "video_extensions": list(policy.video_extensions),
        "exclude_fragments": list(policy.exclude_fragments),
        "exclude_hidden": bool(policy.exclude_hidden),
    }
