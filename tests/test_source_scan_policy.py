from __future__ import annotations

from pathlib import Path

import pytest

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.source_scan_policy import SourceScanPolicy


def make_catalog(tmp_path: Path):
    settings = Settings(profile_path=str(tmp_path), database_backend="sqlite")
    catalog = Catalog(DatabaseEngine(settings))
    catalog.initialize()
    source = catalog.sync_sources([{"label": "Photos", "uri": "/srv/photos"}])[0]
    return catalog, source


def test_source_scan_policy_roundtrip_and_global_inheritance(tmp_path: Path) -> None:
    catalog, source = make_catalog(tmp_path)

    assert catalog.get_source_scan_policy(source.id) is None

    catalog.set_source_scan_policy(
        source.id,
        SourceScanPolicy(
            recursive=False,
            include_videos=True,
            picture_extensions=(".JPG", "nef", "jpg"),
            video_extensions=("MP4", "mov"),
            exclude_fragments=("#Recycle", "@eaDir"),
            exclude_hidden=False,
        ),
    )

    stored = catalog.get_source_scan_policy(source.id)
    assert stored == SourceScanPolicy(
        recursive=False,
        include_videos=True,
        picture_extensions=("jpg", "nef"),
        video_extensions=("mp4", "mov"),
        exclude_fragments=("#recycle", "@eadir"),
        exclude_hidden=False,
    )

    assert catalog.clear_source_scan_policy(source.id) is True
    assert catalog.get_source_scan_policy(source.id) is None
    assert catalog.clear_source_scan_policy(source.id) is False


def test_source_scan_policy_is_removed_with_source(tmp_path: Path) -> None:
    catalog, source = make_catalog(tmp_path)
    catalog.set_source_scan_policy(
        source.id,
        SourceScanPolicy(
            recursive=True,
            include_videos=False,
            picture_extensions=("jpg",),
            video_extensions=("mp4",),
            exclude_fragments=(),
            exclude_hidden=True,
        ),
    )

    assert catalog.delete_source(source.id) is True
    with catalog.engine.transaction() as connection:
        row = catalog.engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM source_scan_policies",
        )
    assert row["total"] == 0


def test_source_scan_policy_rejects_empty_picture_extensions(tmp_path: Path) -> None:
    catalog, source = make_catalog(tmp_path)

    with pytest.raises(ValueError, match="picture extension"):
        catalog.set_source_scan_policy(
            source.id,
            SourceScanPolicy(
                recursive=True,
                include_videos=False,
                picture_extensions=(),
                video_extensions=("mp4",),
                exclude_fragments=(),
                exclude_hidden=True,
            ),
        )
