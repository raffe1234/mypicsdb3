from __future__ import annotations

from pathlib import Path

from mypicsdb3.config import Settings
from mypicsdb3.db.catalog import Catalog
from mypicsdb3.db.engine import DatabaseEngine
from mypicsdb3.music_playlists import MUSIC_TARGET_MANUAL, MUSIC_TARGET_SMART
from mypicsdb3.search import build_global_search_request


def make_catalog(tmp_path: Path) -> Catalog:
    catalog = Catalog(
        DatabaseEngine(
            Settings(profile_path=str(tmp_path), database_backend="sqlite")
        )
    )
    catalog.initialize()
    return catalog


def test_smart_and_manual_collection_music_playlist_roundtrip(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    smart_id = catalog.create_saved_search(
        "Summer", build_global_search_request("summer").query
    )
    manual_id = catalog.create_collection("Family")

    assert catalog.get_music_playlist(MUSIC_TARGET_SMART, smart_id) == ""
    assert catalog.get_music_playlist(MUSIC_TARGET_MANUAL, manual_id) == ""

    assert catalog.set_music_playlist(
        MUSIC_TARGET_SMART, smart_id, " special://music/summer.m3u "
    )
    assert catalog.set_music_playlist(
        MUSIC_TARGET_MANUAL, manual_id, "smb://nas/music/family.pls"
    )
    assert catalog.get_music_playlist(MUSIC_TARGET_SMART, smart_id) == (
        "special://music/summer.m3u"
    )
    assert catalog.get_music_playlist(MUSIC_TARGET_MANUAL, manual_id) == (
        "smb://nas/music/family.pls"
    )
    assert catalog.list_saved_searches()[0]["music_playlist_uri"].endswith(
        "summer.m3u"
    )
    assert catalog.get_saved_search_summary(smart_id)["music_playlist_uri"].endswith(
        "summer.m3u"
    )
    assert catalog.list_collections()[0]["music_playlist_uri"].endswith(
        "family.pls"
    )

    assert catalog.set_music_playlist(
        MUSIC_TARGET_MANUAL, manual_id, "special://music/replacement.m3u8"
    )
    assert catalog.get_music_playlist(MUSIC_TARGET_MANUAL, manual_id).endswith(
        "replacement.m3u8"
    )
    assert catalog.clear_music_playlist(MUSIC_TARGET_MANUAL, manual_id)
    assert not catalog.clear_music_playlist(MUSIC_TARGET_MANUAL, manual_id)
    assert catalog.get_music_playlist(MUSIC_TARGET_MANUAL, manual_id) == ""


def test_missing_target_is_not_given_a_music_playlist(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    assert not catalog.set_music_playlist(
        MUSIC_TARGET_SMART, 999, "special://music/missing.m3u"
    )
    assert catalog.get_music_playlist(MUSIC_TARGET_SMART, 999) == ""


def test_deleting_collection_target_removes_its_playlist_mapping(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    smart_id = catalog.create_saved_search(
        "Summer", build_global_search_request("summer").query
    )
    manual_id = catalog.create_collection("Family")
    assert catalog.set_music_playlist(
        MUSIC_TARGET_SMART, smart_id, "special://music/summer.m3u"
    )
    assert catalog.set_music_playlist(
        MUSIC_TARGET_MANUAL, manual_id, "special://music/family.m3u"
    )

    assert catalog.delete_saved_search(smart_id)
    assert catalog.delete_collection(manual_id)

    with catalog.engine.transaction() as connection:
        total = catalog.engine.fetchone(
            connection,
            "SELECT COUNT(*) AS total FROM collection_music_playlists",
        )["total"]
    assert total == 0
