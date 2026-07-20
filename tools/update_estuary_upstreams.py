#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from estuary_skin import CONFIG_PATH

TAG_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)(?:(?P<stage>a|b|rc)(?P<stage_number>\d+))?-(?P<codename>[A-Za-z0-9]+)$",
    re.IGNORECASE,
)
STAGE_ORDER = {"a": 0, "b": 1, "rc": 2, None: 3}
STAGE_LABEL = {"a": "alpha", "b": "beta", "rc": "rc"}


def parse_tag(tag: str) -> dict[str, Any] | None:
    match = TAG_RE.fullmatch(tag)
    if match is None:
        return None
    stage = match.group("stage")
    return {
        "tag": tag,
        "major": int(match.group("major")),
        "minor": int(match.group("minor")),
        "stage": stage.lower() if stage else None,
        "stage_number": int(match.group("stage_number")) if match.group("stage_number") else 0,
        "codename": match.group("codename"),
    }


def tag_sort_key(parsed: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(parsed["major"]),
        int(parsed["minor"]),
        STAGE_ORDER[parsed["stage"]],
        int(parsed["stage_number"]),
    )


def skin_version_for_tag(tag: str, patch_revision: int) -> str:
    parsed = parse_tag(tag)
    if parsed is None:
        raise ValueError("Unsupported Kodi release tag: %s" % tag)
    if parsed["stage"] is None:
        return "%d.%d.%d" % (parsed["major"], parsed["minor"], patch_revision)
    return "%d.%d.0~%s%d.%d" % (
        parsed["major"],
        parsed["minor"],
        STAGE_LABEL[parsed["stage"]],
        parsed["stage_number"],
        patch_revision,
    )


def fetch_github_releases(url: str, token: str | None = None) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MyPicsDB3-Estuary-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer %s" % token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise RuntimeError("GitHub releases API returned an unexpected response")
    return [item for item in payload if isinstance(item, dict)]


def select_channel_releases(
    releases: Iterable[dict[str, Any]],
    channel: dict[str, Any],
    retain_versions: int,
) -> list[dict[str, str]]:
    matches: list[tuple[dict[str, Any], str]] = []
    for release in releases:
        if release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "")
        parsed = parse_tag(tag)
        if parsed is None:
            continue
        if parsed["major"] != int(channel["kodi_major"]):
            continue
        if parsed["codename"].lower() != str(channel["codename"]).lower():
            continue
        if not bool(channel["include_prereleases"]):
            if release.get("prerelease") or parsed["stage"] is not None:
                continue
        matches.append((parsed, tag))

    matches.sort(key=lambda item: tag_sort_key(item[0]), reverse=True)
    selected = matches[:retain_versions]
    if not selected:
        raise RuntimeError(
            "No Kodi releases matched channel %s %s"
            % (channel["kodi_major"], channel["codename"])
        )

    patch_revision = int(channel["patch_revision"])
    return [
        {
            "ref": tag,
            "archive_url": "https://github.com/xbmc/xbmc/archive/refs/tags/%s.zip" % tag,
            "skin_version": skin_version_for_tag(tag, patch_revision),
        }
        for _, tag in selected
    ]


def update_config_data(
    data: dict[str, Any],
    releases: Iterable[dict[str, Any]],
) -> bool:
    changed = False
    retain_versions = int(data["retain_versions"])
    channels = data.get("channels")
    if not isinstance(channels, dict):
        raise RuntimeError("Estuary configuration has no channels object")
    releases_list = list(releases)
    for channel_name, channel in channels.items():
        if not isinstance(channel, dict):
            raise RuntimeError("Invalid Estuary channel: %s" % channel_name)
        selected = select_channel_releases(releases_list, channel, retain_versions)
        if channel.get("releases") != selected:
            channel["releases"] = selected
            changed = True
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh pinned Estuary releases from the official Kodi GitHub releases"
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument(
        "--releases-json",
        type=Path,
        help="Read a saved GitHub releases API response instead of using the network",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 2 if the configuration would change; do not write it",
    )
    args = parser.parse_args()

    data = json.loads(args.config.read_text(encoding="utf-8"))
    if args.releases_json:
        payload = json.loads(args.releases_json.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("--releases-json must contain a JSON array")
        releases = [item for item in payload if isinstance(item, dict)]
    else:
        releases = fetch_github_releases(
            str(data["github_releases_api"]),
            token=os.environ.get("GITHUB_TOKEN"),
        )

    changed = update_config_data(data, releases)
    if not changed:
        print("Estuary upstream pins are already current")
        return 0
    if args.check:
        print("Estuary upstream pins need updating")
        return 2

    args.config.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Updated Estuary upstream pins:")
    for name, channel in data["channels"].items():
        refs = ", ".join(item["ref"] for item in channel["releases"])
        print(" - %s: %s" % (name, refs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
