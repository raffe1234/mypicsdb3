from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class LocationDetails:
    """Provider-neutral location data already stored in the catalogue.

    This object deliberately contains no provider URL, API key or network side
    effect. A later explicit map action can consume ``coordinates`` without
    coupling catalogue/UI code to a specific map service.
    """

    country: str = ""
    state: str = ""
    city: str = ""
    sublocation: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def has_named_location(self) -> bool:
        return any((self.country, self.state, self.city, self.sublocation))

    @property
    def coordinates(self) -> Optional[Tuple[float, float]]:
        if self.latitude is None or self.longitude is None:
            return None
        return (self.latitude, self.longitude)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _coordinate(value: Any, minimum: float, maximum: float) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        return None
    return parsed


def location_details_from_row(
    row: Dict[str, Any], *, include_coordinates: bool = True
) -> LocationDetails:
    """Normalize catalogue location fields without performing any I/O."""

    latitude = longitude = None
    if include_coordinates:
        latitude = _coordinate(row.get("gps_latitude"), -90.0, 90.0)
        longitude = _coordinate(row.get("gps_longitude"), -180.0, 180.0)
        # Coordinates are useful only as a valid pair. Never surface a lone
        # latitude/longitude to a future provider boundary.
        if latitude is None or longitude is None:
            latitude = longitude = None

    return LocationDetails(
        country=_clean_text(row.get("country")),
        state=_clean_text(row.get("state")),
        city=_clean_text(row.get("city")),
        sublocation=_clean_text(row.get("sublocation")),
        latitude=latitude,
        longitude=longitude,
    )


def format_coordinates(details: LocationDetails) -> str:
    """Return a stable human-readable coordinate pair for local display."""

    coordinates = details.coordinates
    if coordinates is None:
        return ""
    return "%.6f, %.6f" % coordinates
