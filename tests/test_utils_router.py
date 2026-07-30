from __future__ import annotations

from mypicsdb3.router import parse_request
from mypicsdb3.utils import (
    join_uri,
    kodi_image_uri,
    kodi_generated_video_thumbnail_uri,
    normalize_uri,
    plugin_url,
    safe_limit,
    split_csv,
    split_pipe,
)


def test_parse_request_prefers_explicit_query() -> None:
    request = parse_request(
        "plugin://plugin.image.mypicsdb3/recent-taken?limit=5",
        "?limit=15&name=Summer%20trip",
    )
    assert request.route == "recent-taken"
    assert request.params == {"limit": "15", "name": "Summer trip"}


def test_uri_helpers_support_local_and_network_paths() -> None:
    assert normalize_uri(r"C:\\Photos\\2026", directory=True) == "C:/Photos/2026/"
    assert normalize_uri("smb://server//photos///2026", directory=True) == "smb://server/photos/2026/"
    assert join_uri("smb://server/photos/", "Summer/image.jpg") == "smb://server/photos/Summer/image.jpg"
    assert join_uri("/srv/photos/", "Summer", directory=True) == "/srv/photos/Summer/"


def test_plugin_url_and_setting_parsers() -> None:
    url = plugin_url("plugin://plugin.image.mypicsdb3", "camera", make="Canon", model="EOS R6")
    assert url == "plugin://plugin.image.mypicsdb3/camera?make=Canon&model=EOS+R6"
    nested_url = plugin_url("plugin://plugin.image.mypicsdb3/sources", "action/toggle-source", id=7)
    assert nested_url == "plugin://plugin.image.mypicsdb3/action/toggle-source?id=7"
    assert safe_limit("9999", 15) == 500
    assert split_csv(".JPG, png, JPG") == ("jpg", "png")
    assert split_pipe("@eaDir| #recycle |") == ("@eadir", "#recycle")


def test_kodi_generated_video_thumbnail_uri_encodes_network_and_unicode_paths() -> None:
    assert kodi_generated_video_thumbnail_uri("smb://server/Home videos/clip #1.mp4") == (
        "image://video@smb%3A%2F%2Fserver%2FHome%20videos%2Fclip%20%231.mp4/"
    )
    assert kodi_generated_video_thumbnail_uri("nfs://nas/Åland/film.mov") == (
        "image://video@nfs%3A%2F%2Fnas%2F%C3%85land%2Ffilm.mov/"
    )
    assert kodi_generated_video_thumbnail_uri("") == ""


def test_kodi_image_uri_creates_one_stable_texture_cache_key() -> None:
    assert kodi_image_uri("smb://server/Home pictures/image #1.jpg") == (
        "image://smb%3A%2F%2Fserver%2FHome%20pictures%2Fimage%20%231.jpg/"
    )
    assert kodi_image_uri("image://already%2Fencoded/") == "image://already%2Fencoded/"
    assert kodi_image_uri("") == ""
