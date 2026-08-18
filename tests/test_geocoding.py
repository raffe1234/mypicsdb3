from __future__ import annotations

import json
import pytest

from mypicsdb3.geocoding import (
    NominatimReverseGeocoder,
    ResolvedLocation,
    ReverseGeocodingError,
    load_location_enrichment,
    merge_location,
    normalize_nominatim_endpoint,
    parse_nominatim_geocodejson,
    save_location_enrichment,
)


class FakeCatalog:
    def __init__(self):
        self.meta = {}

    def meta_value(self, key):
        return self.meta.get(key)

    def set_meta_value(self, key, value):
        self.meta[key] = str(value)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self, _size=-1):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


def geocodejson_payload():
    return {
        "type": "FeatureCollection",
        "geocoding": {
            "version": "0.1.0",
            "attribution": "Data © OpenStreetMap contributors, ODbL 1.0",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "geocoding": {
                        "type": "house",
                        "label": "Benidorm, Alicante, Comunitat Valenciana, Spain",
                        "locality": "Levante",
                        "city": "Benidorm",
                        "county": "Alicante",
                        "state": "Comunitat Valenciana",
                        "country": "Spain",
                    }
                },
                "geometry": {"type": "Point", "coordinates": [-0.1334, 38.5367]},
            }
        ],
    }


def test_parse_geocodejson_uses_stable_named_location_fields() -> None:
    result = parse_nominatim_geocodejson(geocodejson_payload())

    assert result.country == "Spain"
    assert result.state == "Comunitat Valenciana"
    assert result.city == "Benidorm"
    assert result.sublocation == "Levante"
    assert result.provider == "Nominatim / OpenStreetMap"
    assert "OpenStreetMap" in (result.attribution or "")


def test_nominatim_lookup_sends_only_coordinate_query_and_caches_result() -> None:
    catalog = FakeCatalog()
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(geocodejson_payload())

    geocoder = NominatimReverseGeocoder(
        catalog,
        endpoint="https://nominatim.openstreetmap.org/",
        user_agent="MyPicsDB3/0.8.28 (test)",
        opener=opener,
    )
    result = geocoder.resolve(38.536747, -0.133435)

    assert result.city == "Benidorm"
    assert result.from_cache is False
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 10
    assert request.get_header("User-agent") == "MyPicsDB3/0.8.28 (test)"
    assert "lat=38.5367470" in request.full_url
    assert "lon=-0.1334350" in request.full_url
    assert "format=geocodejson" in request.full_url
    assert "layer=address" in request.full_url
    assert "filename" not in request.full_url.lower()

    cached = geocoder.resolve(38.536747, -0.133435)
    assert cached.city == "Benidorm"
    assert cached.from_cache is True
    assert len(calls) == 1



def test_nominatim_cache_misses_respect_persistent_request_interval() -> None:
    catalog = FakeCatalog()
    calls = []
    sleeps = []
    now = [1000.0]

    def clock():
        return now[0]

    def sleeper(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def opener(request, timeout):
        calls.append((request, timeout, now[0]))
        return FakeResponse(geocodejson_payload())

    geocoder = NominatimReverseGeocoder(
        catalog,
        user_agent="MyPicsDB3/0.8.28 (test)",
        opener=opener,
        clock=clock,
        sleeper=sleeper,
        min_request_interval_seconds=1.1,
    )
    geocoder.resolve(38.536747, -0.133435)
    now[0] += 0.2
    geocoder.resolve(38.536800, -0.133500)

    assert len(calls) == 2
    assert sleeps == pytest.approx([0.9])
    assert calls[1][2] - calls[0][2] == pytest.approx(1.1)


def test_endpoint_must_be_switchable_http_or_https_base_url() -> None:
    assert normalize_nominatim_endpoint("https://example.invalid/nominatim/") == (
        "https://example.invalid/nominatim"
    )
    assert normalize_nominatim_endpoint("http://127.0.0.1:8080/reverse") == (
        "http://127.0.0.1:8080"
    )
    with pytest.raises(ReverseGeocodingError):
        normalize_nominatim_endpoint("file:///tmp/nominatim")
    with pytest.raises(ReverseGeocodingError):
        normalize_nominatim_endpoint("https://example.invalid/?token=secret")


def test_uri_enrichment_is_local_and_only_fills_missing_embedded_fields() -> None:
    catalog = FakeCatalog()
    result = ResolvedLocation(
        country="Spain",
        state="Comunitat Valenciana",
        city="Benidorm",
        sublocation="Levante",
        attribution="© OpenStreetMap contributors",
    )
    save_location_enrichment(catalog, "smb://server/photos/one.jpg", result)
    loaded = load_location_enrichment(catalog, "smb://server/photos/one.jpg")

    assert loaded is not None
    assert loaded.city == "Benidorm"
    merged = merge_location(
        {"city": "Embedded city", "country": None, "state": None, "sublocation": None},
        loaded,
    )
    assert merged["city"] == "Embedded city"
    assert merged["country"] == "Spain"
    assert merged["state"] == "Comunitat Valenciana"
    assert merged["sublocation"] == "Levante"


def test_bulk_reverse_geocode_cache_reuses_four_decimal_coordinate_cell() -> None:
    from mypicsdb3.geocoding import (
        ResolvedLocation,
        load_bulk_cached_reverse_geocoding,
        save_bulk_cached_reverse_geocoding,
    )

    catalog = FakeCatalog()
    result = ResolvedLocation(country="Sweden", city="Stockholm")
    endpoint = "https://nominatim.openstreetmap.org"
    save_bulk_cached_reverse_geocoding(catalog, endpoint, 59.32931, 18.06861, result)

    cached = load_bulk_cached_reverse_geocoding(
        catalog, endpoint, 59.32934, 18.06864
    )
    assert cached is not None
    assert cached.city == "Stockholm"
    assert cached.from_cache is True
