from __future__ import annotations

from mypicsdb3.geocoding import (
    ResolvedLocation,
    reverse_geocoding_cache_key,
)
from mypicsdb3.location_enrichment import (
    BulkLocationEnricher,
    CHECKPOINT_KEY,
    analyse_location_coverage,
    estimate_public_nominatim_seconds,
)


class FakeCatalog:
    def __init__(self):
        self.meta = {}
        self.rows = [
            {
                "id": 1,
                "uri": "smb://server/photos/one.jpg",
                "filename": "one.jpg",
                "gps_latitude": 59.32931,
                "gps_longitude": 18.06861,
                "country": None,
                "state": None,
                "city": None,
                "sublocation": None,
            },
            {
                "id": 2,
                "uri": "smb://server/photos/two.jpg",
                "filename": "two.jpg",
                "gps_latitude": 59.32934,
                "gps_longitude": 18.06864,
                "country": None,
                "state": None,
                "city": None,
                "sublocation": None,
            },
        ]
        self.lock_refreshes = 0

    def meta_value(self, key):
        return self.meta.get(key)

    def set_meta_value(self, key, value):
        self.meta[key] = str(value)

    def meta_keys_with_prefix(self, prefix):
        return sorted(key for key in self.meta if str(key).startswith(str(prefix)))

    def location_coverage_summary(self, max_picture_id=None, metadata_index_hash=None):
        rows = [
            row for row in self.rows
            if max_picture_id is None or row["id"] <= max_picture_id
        ]
        gps_rows = [
            row for row in rows
            if row.get("gps_latitude") is not None and row.get("gps_longitude") is not None
        ]
        needs = [row for row in gps_rows if self._candidate(row)]
        return {
            "total_pictures": len(rows),
            "gps_pictures": len(gps_rows),
            "gps_complete": len(gps_rows) - len(needs),
            "needs_lookup": len(needs),
            "metadata_current_pictures": len(rows),
            "max_picture_id": max((row["id"] for row in rows), default=0),
        }

    def location_analysis_coordinate_rows(self, after_id, max_picture_id, limit):
        return [
            {
                "id": row["id"],
                "uri": row["uri"],
                "gps_latitude": row["gps_latitude"],
                "gps_longitude": row["gps_longitude"],
            }
            for row in self.rows
            if after_id < row["id"] <= max_picture_id and self._candidate(row)
        ][:limit]

    def location_enrichment_picture_horizon(self):
        candidates = [row for row in self.rows if self._candidate(row)]
        return (len(candidates), max((row["id"] for row in candidates), default=0))

    def pictures_for_location_enrichment(self, after_id, max_picture_id, limit):
        return [
            dict(row)
            for row in self.rows
            if after_id < row["id"] <= max_picture_id and self._candidate(row)
        ][:limit]

    def update_picture_named_location(self, picture_id, location, fill_only=True):
        row = next(row for row in self.rows if row["id"] == picture_id)
        for field in ("country", "state", "city", "sublocation"):
            incoming = location.get(field)
            if incoming and (not fill_only or not row.get(field)):
                row[field] = incoming
        return dict(row)

    def refresh_lock(self, name, owner, ttl):
        self.lock_refreshes += 1
        return True

    @staticmethod
    def _candidate(row):
        return all(row.get(key) is not None for key in ("gps_latitude", "gps_longitude")) and any(
            not str(row.get(field) or "").strip()
            for field in ("country", "state", "city", "sublocation")
        )


class FakeGeocoder:
    def __init__(self):
        self.calls = []
        self.min_request_interval_seconds = 1.1

    def resolve(self, latitude, longitude):
        self.calls.append((latitude, longitude))
        return ResolvedLocation(
            country="Sweden",
            state="Stockholm County",
            city="Stockholm",
            sublocation="Norrmalm",
            label="Stockholm, Sweden",
            provider="Nominatim / OpenStreetMap",
            from_cache=False,
        )


def test_bulk_enrichment_reuses_roughly_ten_metre_coordinate_cell() -> None:
    catalog = FakeCatalog()
    geocoder = FakeGeocoder()
    enricher = BulkLocationEnricher(
        catalog,
        geocoder,
        "https://nominatim.openstreetmap.org",
        "test-owner",
        clock=lambda: 1000.0,
    )

    stats = enricher.run()

    assert stats.completed is True
    assert stats.processed == 2
    assert stats.updated == 2
    assert stats.network_lookups == 1
    assert stats.cache_hits == 1
    assert stats.failed == 0
    assert len(geocoder.calls) == 1
    assert {row["city"] for row in catalog.rows} == {"Stockholm"}
    assert catalog.meta.get(CHECKPOINT_KEY) == ""
    assert any(key.startswith("reverse_geocode_bulk_cache:v1:") for key in catalog.meta)


def test_bulk_enrichment_checkpoint_resumes_after_soft_stop() -> None:
    catalog = FakeCatalog()
    first_geocoder = FakeGeocoder()
    first = BulkLocationEnricher(
        catalog,
        first_geocoder,
        "https://nominatim.openstreetmap.org",
        "first-owner",
        clock=lambda: 1000.0,
    )

    first_stats = first.run(cancelled=lambda: bool(catalog.rows[0]["city"]))

    assert first_stats.completed is False
    assert first_stats.processed == 1
    checkpoint = first.checkpoint()
    assert checkpoint is not None
    assert checkpoint["last_picture_id"] == 1

    second_geocoder = FakeGeocoder()
    second = BulkLocationEnricher(
        catalog,
        second_geocoder,
        "https://nominatim.openstreetmap.org",
        "second-owner",
        clock=lambda: 1001.0,
    )
    second_stats = second.run()

    assert second_stats.resumed is True
    assert second_stats.completed is True
    assert second_stats.processed == 2
    assert second_stats.network_lookups == 1
    assert second_stats.cache_hits == 1
    assert second_geocoder.calls == []


def test_location_coverage_analysis_is_local_and_estimates_bulk_reuse() -> None:
    catalog = FakeCatalog()

    analysis = analyse_location_coverage(
        catalog, "https://nominatim.openstreetmap.org"
    )

    assert analysis.total_pictures == 2
    assert analysis.gps_pictures == 2
    assert analysis.gps_complete == 0
    assert analysis.needs_lookup == 2
    assert analysis.unique_exact == 2
    assert analysis.bulk_cells_10m == 1
    assert analysis.estimated_online_lookups == 1
    assert analysis.cached_picture_rows == 0
    assert analysis.cached_bulk_rows == 0
    assert analysis.cached_exact_rows == 0
    assert analysis.estimated_bulk_reuse_rows == 1
    assert catalog.rows[0]["city"] is None
    assert catalog.meta == {}


def test_location_coverage_analysis_simulates_exact_cache_becoming_bulk_cache() -> None:
    catalog = FakeCatalog()
    exact_key = reverse_geocoding_cache_key(
        "https://nominatim.openstreetmap.org",
        catalog.rows[0]["gps_latitude"],
        catalog.rows[0]["gps_longitude"],
    )
    catalog.meta[exact_key] = "cached exact provider result"

    analysis = analyse_location_coverage(
        catalog, "https://nominatim.openstreetmap.org"
    )

    assert analysis.estimated_online_lookups == 0
    assert analysis.cached_exact_rows == 1
    assert analysis.cached_bulk_rows == 0
    assert analysis.estimated_bulk_reuse_rows == 1


def test_public_nominatim_estimate_slows_after_one_day() -> None:
    one_day_capacity = int((24 * 60 * 60) // 1.1) + 1
    before = estimate_public_nominatim_seconds(one_day_capacity)
    after = estimate_public_nominatim_seconds(one_day_capacity + 1)

    assert before <= 24 * 60 * 60
    assert after - before >= 15.0
