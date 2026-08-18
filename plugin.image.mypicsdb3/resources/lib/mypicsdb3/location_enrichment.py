from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set, Tuple

from .db.locks import LOCATION_ENRICHMENT_LOCK_NAME
from .geocoding import (
    MIN_REQUEST_INTERVAL_SECONDS,
    PUBLIC_NOMINATIM_LONG_RUN_AFTER_SECONDS,
    PUBLIC_NOMINATIM_LONG_RUN_INTERVAL_SECONDS,
    ReverseGeocodingError,
    bulk_reverse_geocoding_cache_key,
    enrichment_key,
    is_public_nominatim_endpoint,
    load_bulk_cached_reverse_geocoding,
    load_location_enrichment,
    normalize_nominatim_endpoint,
    reverse_geocoding_cache_key,
    reverse_geocoding_cache_prefix,
    save_bulk_cached_reverse_geocoding,
    save_location_enrichment,
)


CHECKPOINT_KEY = "location_bulk_checkpoint:v1"
CHECKPOINT_VERSION = 1
LOCK_TTL_SECONDS = 1800
LOCK_REFRESH_SECONDS = 60.0


@dataclass
class LocationEnrichmentStats:
    requested: int = 0
    processed: int = 0
    updated: int = 0
    cache_hits: int = 0
    network_lookups: int = 0
    failed: int = 0
    resumed: bool = False
    completed: bool = False
    last_picture_id: int = 0


@dataclass(frozen=True)
class LocationCoverageAnalysis:
    total_pictures: int = 0
    gps_pictures: int = 0
    gps_complete: int = 0
    needs_lookup: int = 0
    metadata_current_pictures: int = 0
    metadata_refresh_needed: int = 0
    unique_exact: int = 0
    bulk_cells_10m: int = 0
    grid_cells_25m: int = 0
    grid_cells_50m: int = 0
    grid_cells_100m: int = 0
    cached_picture_rows: int = 0
    cached_bulk_rows: int = 0
    cached_exact_rows: int = 0
    estimated_bulk_reuse_rows: int = 0
    estimated_online_lookups: int = 0
    estimated_public_seconds: float = 0.0


def _approx_grid_cell(latitude: float, longitude: float, metres: float) -> Tuple[int, int, int]:
    """Return a deterministic approximate ground-distance bucket for comparison.

    The production bulk cache remains the four-decimal provider key. These extra
    25/50/100 m figures are diagnostics only. Quantising Earth-centred Cartesian
    coordinates keeps the comparison dependency-free and avoids longitude-degree
    distortion at higher latitudes.
    """

    lat = math.radians(max(-90.0, min(90.0, float(latitude))))
    lon = math.radians(float(longitude))
    radius = 6371008.8
    cos_lat = math.cos(lat)
    x = radius * cos_lat * math.cos(lon)
    y = radius * cos_lat * math.sin(lon)
    z = radius * math.sin(lat)
    size = max(1.0, float(metres))
    return (
        int(math.floor(x / size)),
        int(math.floor(y / size)),
        int(math.floor(z / size)),
    )


def estimate_public_nominatim_seconds(lookups: int) -> float:
    """Approximate the patch's public-Nominatim throttle for one resumable run."""

    count = max(0, int(lookups))
    if count <= 1:
        return 0.0
    normal_intervals = max(0, count - 1)
    normal_capacity = int(PUBLIC_NOMINATIM_LONG_RUN_AFTER_SECONDS // MIN_REQUEST_INTERVAL_SECONDS)
    if normal_intervals <= normal_capacity:
        return float(normal_intervals) * MIN_REQUEST_INTERVAL_SECONDS
    remaining = normal_intervals - normal_capacity
    return (
        float(normal_capacity) * MIN_REQUEST_INTERVAL_SECONDS
        + float(remaining) * PUBLIC_NOMINATIM_LONG_RUN_INTERVAL_SECONDS
    )


def analyse_location_coverage(
    catalog,
    endpoint: str,
    metadata_index_hash: Optional[str] = None,
) -> LocationCoverageAnalysis:
    """Inspect stored GPS coverage and simulate cache reuse without network I/O.

    The analysis deliberately does not open source images. ``metadata_index_hash``
    lets the caller prove whether the catalogue rows were indexed with the current
    metadata settings before treating the stored-GPS count as complete.
    """

    normalized_endpoint = normalize_nominatim_endpoint(endpoint)
    first = catalog.location_coverage_summary(metadata_index_hash=metadata_index_hash)
    max_picture_id = int(first.get("max_picture_id") or 0)
    if max_picture_id <= 0:
        total = int(first.get("total_pictures") or 0)
        current = int(first.get("metadata_current_pictures") or 0)
        return LocationCoverageAnalysis(
            total_pictures=total,
            gps_pictures=int(first.get("gps_pictures") or 0),
            gps_complete=int(first.get("gps_complete") or 0),
            needs_lookup=int(first.get("needs_lookup") or 0),
            metadata_current_pictures=current,
            metadata_refresh_needed=max(0, total - current),
        )

    summary = catalog.location_coverage_summary(
        max_picture_id, metadata_index_hash=metadata_index_hash
    )
    enrichment_keys: Set[str] = set(catalog.meta_keys_with_prefix("location_enrichment:v1:"))
    exact_cache_keys: Set[str] = set(
        catalog.meta_keys_with_prefix(reverse_geocoding_cache_prefix(normalized_endpoint))
    )
    bulk_cache_keys: Set[str] = set(
        catalog.meta_keys_with_prefix(
            reverse_geocoding_cache_prefix(normalized_endpoint, bulk=True)
        )
    )
    simulated_bulk_keys = set(bulk_cache_keys)

    unique_exact: Set[Tuple[float, float]] = set()
    bulk_cells: Set[str] = set()
    grids_25: Set[Tuple[int, int, int]] = set()
    grids_50: Set[Tuple[int, int, int]] = set()
    grids_100: Set[Tuple[int, int, int]] = set()
    cached_picture_rows = 0
    cached_bulk_rows = 0
    cached_exact_rows = 0
    estimated_bulk_reuse_rows = 0
    estimated_online = 0

    after_id = 0
    while True:
        rows = catalog.location_analysis_coordinate_rows(after_id, max_picture_id, 5000)
        if not rows:
            break
        for row in rows:
            picture_id = int(row.get("id") or 0)
            if picture_id <= 0:
                continue
            after_id = picture_id
            latitude = float(row.get("gps_latitude"))
            longitude = float(row.get("gps_longitude"))
            unique_exact.add((latitude, longitude))
            bulk_key = bulk_reverse_geocoding_cache_key(
                normalized_endpoint, latitude, longitude
            )
            exact_key = reverse_geocoding_cache_key(normalized_endpoint, latitude, longitude)
            bulk_cells.add(bulk_key)
            grids_25.add(_approx_grid_cell(latitude, longitude, 25.0))
            grids_50.add(_approx_grid_cell(latitude, longitude, 50.0))
            grids_100.add(_approx_grid_cell(latitude, longitude, 100.0))

            if enrichment_key(str(row.get("uri") or "")) in enrichment_keys:
                cached_picture_rows += 1
                continue
            if bulk_key in simulated_bulk_keys:
                if bulk_key in bulk_cache_keys:
                    cached_bulk_rows += 1
                else:
                    estimated_bulk_reuse_rows += 1
                continue
            if exact_key in exact_cache_keys:
                cached_exact_rows += 1
                simulated_bulk_keys.add(bulk_key)
                continue
            estimated_online += 1
            simulated_bulk_keys.add(bulk_key)

    public_seconds = (
        estimate_public_nominatim_seconds(estimated_online)
        if is_public_nominatim_endpoint(normalized_endpoint)
        else 0.0
    )
    total_pictures = int(summary.get("total_pictures") or 0)
    metadata_current_pictures = int(summary.get("metadata_current_pictures") or 0)
    return LocationCoverageAnalysis(
        total_pictures=total_pictures,
        gps_pictures=int(summary.get("gps_pictures") or 0),
        gps_complete=int(summary.get("gps_complete") or 0),
        needs_lookup=int(summary.get("needs_lookup") or 0),
        metadata_current_pictures=metadata_current_pictures,
        metadata_refresh_needed=max(0, total_pictures - metadata_current_pictures),
        unique_exact=len(unique_exact),
        bulk_cells_10m=len(bulk_cells),
        grid_cells_25m=len(grids_25),
        grid_cells_50m=len(grids_50),
        grid_cells_100m=len(grids_100),
        cached_picture_rows=cached_picture_rows,
        cached_bulk_rows=cached_bulk_rows,
        cached_exact_rows=cached_exact_rows,
        estimated_bulk_reuse_rows=estimated_bulk_reuse_rows,
        estimated_online_lookups=estimated_online,
        estimated_public_seconds=public_seconds,
    )


class BulkLocationEnricher:
    """Explicit serial GPS -> named-location enrichment for existing picture rows.

    The caller owns the catalogue-wide location-enrichment lock. This worker keeps
    a stable picture-ID horizon, persists resumable progress in catalogue meta and
    uses a coarse (~10 m) cache only for this explicit bulk path. Source files are
    never opened and only latitude/longitude reach the configured geocoder.
    """

    def __init__(
        self,
        catalog,
        geocoder,
        endpoint: str,
        lock_owner: str,
        *,
        clock: Optional[Callable[[], float]] = None,
        logger=None,
    ):
        self.catalog = catalog
        self.geocoder = geocoder
        self.endpoint = normalize_nominatim_endpoint(endpoint)
        self.lock_owner = str(lock_owner or "")
        self.clock = clock or time.time
        self.logger = logger
        self._last_lock_refresh = float(self.clock())

    def _load_checkpoint(self) -> Optional[Dict[str, Any]]:
        raw = self.catalog.meta_value(CHECKPOINT_KEY)
        if not raw:
            return None
        try:
            value = json.loads(str(raw))
        except Exception:
            return None
        if not isinstance(value, dict) or int(value.get("version") or 0) != CHECKPOINT_VERSION:
            return None
        if str(value.get("endpoint") or "") != self.endpoint:
            return None
        return value

    def checkpoint(self) -> Optional[Dict[str, Any]]:
        value = self._load_checkpoint()
        return dict(value) if value else None

    def discard_checkpoint(self) -> None:
        # The meta store has no delete primitive by design. An empty value is
        # treated as absent by the reader and keeps schema 9 unchanged.
        self.catalog.set_meta_value(CHECKPOINT_KEY, "")

    def _save_checkpoint(self, state: Dict[str, Any]) -> None:
        self.catalog.set_meta_value(
            CHECKPOINT_KEY,
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    def _refresh_lock_if_due(self) -> None:
        now = float(self.clock())
        if now - self._last_lock_refresh < LOCK_REFRESH_SECONDS:
            return
        if not self.catalog.refresh_lock(
            LOCATION_ENRICHMENT_LOCK_NAME, self.lock_owner, LOCK_TTL_SECONDS
        ):
            raise RuntimeError("Location-enrichment catalogue lock was lost")
        self._last_lock_refresh = now

    def _apply_public_service_interval(self, started_at: float) -> None:
        if not is_public_nominatim_endpoint(self.endpoint):
            return
        elapsed = max(0.0, float(self.clock()) - float(started_at))
        interval = (
            PUBLIC_NOMINATIM_LONG_RUN_INTERVAL_SECONDS
            if elapsed >= PUBLIC_NOMINATIM_LONG_RUN_AFTER_SECONDS
            else MIN_REQUEST_INTERVAL_SECONDS
        )
        if hasattr(self.geocoder, "min_request_interval_seconds"):
            self.geocoder.min_request_interval_seconds = interval

    @staticmethod
    def _named_tuple(row: Dict[str, Any]):
        return tuple(str(row.get(field) or "").strip() for field in ("country", "state", "city", "sublocation"))

    def run(
        self,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[LocationEnrichmentStats, str], None]] = None,
        *,
        restart: bool = False,
    ) -> LocationEnrichmentStats:
        if restart:
            self.discard_checkpoint()
        checkpoint = self._load_checkpoint()
        resumed = checkpoint is not None

        if checkpoint is None:
            total, max_picture_id = self.catalog.location_enrichment_picture_horizon()
            state: Dict[str, Any] = {
                "version": CHECKPOINT_VERSION,
                "endpoint": self.endpoint,
                "max_picture_id": int(max_picture_id),
                "total": int(total),
                "last_picture_id": 0,
                "processed": 0,
                "updated": 0,
                "cache_hits": 0,
                "network_lookups": 0,
                "failed": 0,
                "started_at": float(self.clock()),
            }
        else:
            state = dict(checkpoint)
            max_picture_id = int(state.get("max_picture_id") or 0)

        stats = LocationEnrichmentStats(
            requested=max(0, int(state.get("total") or 0)),
            processed=max(0, int(state.get("processed") or 0)),
            updated=max(0, int(state.get("updated") or 0)),
            cache_hits=max(0, int(state.get("cache_hits") or 0)),
            network_lookups=max(0, int(state.get("network_lookups") or 0)),
            failed=max(0, int(state.get("failed") or 0)),
            resumed=resumed,
            last_picture_id=max(0, int(state.get("last_picture_id") or 0)),
        )
        if stats.requested <= 0 or max_picture_id <= 0:
            stats.completed = True
            self.discard_checkpoint()
            return stats

        if checkpoint is None:
            self._save_checkpoint(state)

        batch_size = 200
        started_at = float(state.get("started_at") or self.clock())

        while True:
            if cancelled and cancelled():
                return stats
            self._refresh_lock_if_due()
            rows = self.catalog.pictures_for_location_enrichment(
                stats.last_picture_id, max_picture_id, batch_size
            )
            if not rows:
                stats.completed = True
                self.discard_checkpoint()
                return stats

            for row in rows:
                if cancelled and cancelled():
                    return stats
                self._refresh_lock_if_due()
                picture_id = int(row.get("id") or 0)
                filename = str(row.get("filename") or "")
                latitude = float(row.get("gps_latitude"))
                longitude = float(row.get("gps_longitude"))
                try:
                    result = load_location_enrichment(
                        self.catalog, str(row.get("uri") or "")
                    )
                    cache_hit = result is not None
                    if result is None:
                        result = load_bulk_cached_reverse_geocoding(
                            self.catalog, self.endpoint, latitude, longitude
                        )
                        cache_hit = result is not None
                    if result is None:
                        self._apply_public_service_interval(started_at)
                        result = self.geocoder.resolve(latitude, longitude)
                        cache_hit = bool(result.from_cache)
                        if result.has_named_location:
                            save_bulk_cached_reverse_geocoding(
                                self.catalog, self.endpoint, latitude, longitude, result
                            )
                    if not result.has_named_location:
                        raise ReverseGeocodingError(
                            "The reverse geocoder returned no named location"
                        )

                    before = self._named_tuple(row)
                    save_location_enrichment(
                        self.catalog, str(row.get("uri") or ""), result
                    )
                    updated_row = self.catalog.update_picture_named_location(
                        picture_id, result.as_location_dict(), fill_only=True
                    )
                    if updated_row is None:
                        raise ReverseGeocodingError(
                            "Picture was not found while saving location"
                        )
                    if self._named_tuple(updated_row) != before:
                        stats.updated += 1
                    if cache_hit:
                        stats.cache_hits += 1
                    else:
                        stats.network_lookups += 1
                except Exception as exc:
                    stats.failed += 1
                    if self.logger:
                        self.logger.warning(
                            "Bulk location enrichment failed for picture id %d: %s",
                            picture_id,
                            exc,
                        )

                stats.processed += 1
                stats.last_picture_id = picture_id
                state.update(
                    {
                        "last_picture_id": stats.last_picture_id,
                        "processed": stats.processed,
                        "updated": stats.updated,
                        "cache_hits": stats.cache_hits,
                        "network_lookups": stats.network_lookups,
                        "failed": stats.failed,
                    }
                )
                self._save_checkpoint(state)
                if progress:
                    progress(stats, filename)
