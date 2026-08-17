from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .utils import sha256_text, utc_now


DEFAULT_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 262144
CACHE_COORDINATE_DECIMALS = 5
MIN_REQUEST_INTERVAL_SECONDS = 1.1


class ReverseGeocodingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedLocation:
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    sublocation: Optional[str] = None
    label: Optional[str] = None
    attribution: Optional[str] = None
    provider: str = "Nominatim"
    from_cache: bool = False

    @property
    def has_named_location(self) -> bool:
        return any((self.country, self.state, self.city, self.sublocation))

    def as_location_dict(self) -> Dict[str, Optional[str]]:
        return {
            "country": self.country,
            "state": self.state,
            "city": self.city,
            "sublocation": self.sublocation,
        }


def _clean_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def normalize_nominatim_endpoint(value: Any) -> str:
    raw = str(value or DEFAULT_NOMINATIM_ENDPOINT).strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ReverseGeocodingError("Nominatim server URL must be an http(s) URL")
    if parts.query or parts.fragment:
        raise ReverseGeocodingError("Nominatim server URL must not include query parameters or a fragment")
    path = parts.path.rstrip("/")
    if path.endswith("/reverse"):
        path = path[: -len("/reverse")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def _provider_token(endpoint: str) -> str:
    return sha256_text(normalize_nominatim_endpoint(endpoint))[:16]


def _rate_limit_key(endpoint: str) -> str:
    return "reverse_geocode_last_request:v1:%s" % _provider_token(endpoint)


def _cache_key(endpoint: str, latitude: float, longitude: float) -> str:
    return "reverse_geocode_cache:v1:%s:%.*f:%.*f" % (
        _provider_token(endpoint),
        CACHE_COORDINATE_DECIMALS,
        float(latitude),
        CACHE_COORDINATE_DECIMALS,
        float(longitude),
    )


def enrichment_key(uri: str) -> str:
    return "location_enrichment:v1:%s" % sha256_text(str(uri or ""))


def _parse_feature(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    features = payload.get("features")
    if isinstance(features, list):
        feature = features[0] if features else None
    elif isinstance(features, dict):
        feature = features
    else:
        feature = None
    if not isinstance(feature, Mapping):
        raise ReverseGeocodingError("Reverse geocoding returned no location result")
    properties = feature.get("properties")
    if not isinstance(properties, Mapping):
        raise ReverseGeocodingError("Reverse geocoding response is missing properties")
    geocoding = properties.get("geocoding")
    if not isinstance(geocoding, Mapping):
        raise ReverseGeocodingError("Reverse geocoding response is missing address details")
    return geocoding


def parse_nominatim_geocodejson(payload: Mapping[str, Any]) -> ResolvedLocation:
    geocoding = _parse_feature(payload)
    top = payload.get("geocoding")
    top_geocoding = top if isinstance(top, Mapping) else {}

    country = _clean_text(geocoding.get("country"))
    state = _clean_text(geocoding.get("state")) or _clean_text(geocoding.get("county"))
    city = _clean_text(geocoding.get("city"))
    locality = _clean_text(geocoding.get("locality"))
    district = _clean_text(geocoding.get("district"))
    if city is None:
        city = locality or district

    sublocation = district
    if sublocation and city and sublocation.casefold() == city.casefold():
        sublocation = None
    if sublocation is None and locality and (not city or locality.casefold() != city.casefold()):
        sublocation = locality

    return ResolvedLocation(
        country=country,
        state=state,
        city=city,
        sublocation=sublocation,
        label=_clean_text(geocoding.get("label")),
        attribution=_clean_text(top_geocoding.get("attribution")),
        provider="Nominatim / OpenStreetMap",
        from_cache=False,
    )


def _result_to_json(result: ResolvedLocation) -> str:
    return json.dumps(
        {
            "version": 1,
            "country": result.country,
            "state": result.state,
            "city": result.city,
            "sublocation": result.sublocation,
            "label": result.label,
            "attribution": result.attribution,
            "provider": result.provider,
            "cached_at": utc_now(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _result_from_json(value: str) -> Optional[ResolvedLocation]:
    try:
        payload = json.loads(str(value or ""))
    except Exception:
        return None
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != 1:
        return None
    result = ResolvedLocation(
        country=_clean_text(payload.get("country")),
        state=_clean_text(payload.get("state")),
        city=_clean_text(payload.get("city")),
        sublocation=_clean_text(payload.get("sublocation")),
        label=_clean_text(payload.get("label")),
        attribution=_clean_text(payload.get("attribution")),
        provider=_clean_text(payload.get("provider")) or "Nominatim / OpenStreetMap",
        from_cache=True,
    )
    return result



def load_cached_reverse_geocoding(
    catalog,
    endpoint: str,
    latitude: float,
    longitude: float,
) -> Optional[ResolvedLocation]:
    """Return an existing provider+coordinate cache entry without network I/O."""

    try:
        key = _cache_key(endpoint, float(latitude), float(longitude))
    except (TypeError, ValueError, ReverseGeocodingError):
        return None
    raw = catalog.meta_value(key)
    if not raw:
        return None
    return _result_from_json(raw)


def load_location_enrichment(
    catalog,
    uri: str,
    connection=None,
) -> Optional[ResolvedLocation]:
    if not uri:
        return None
    getter = None
    if connection is not None:
        candidate = getattr(catalog, "meta_value_in_connection", None)
        if callable(candidate):
            getter = lambda key: candidate(connection, key)
    if getter is None:
        candidate = getattr(catalog, "meta_value", None)
        if callable(candidate):
            getter = candidate
    if getter is None:
        return None
    raw = getter(enrichment_key(uri))
    if not raw:
        return None
    return _result_from_json(raw)


def save_location_enrichment(catalog, uri: str, result: ResolvedLocation) -> None:
    setter = getattr(catalog, "set_meta_value", None)
    if not callable(setter) or not uri:
        return
    setter(enrichment_key(uri), _result_to_json(result))


def merge_location(
    embedded: Optional[Mapping[str, Any]],
    enrichment: Optional[ResolvedLocation],
) -> Dict[str, Optional[str]]:
    values = dict(embedded or {})
    merged: Dict[str, Optional[str]] = {
        "country": _clean_text(values.get("country")),
        "state": _clean_text(values.get("state")),
        "city": _clean_text(values.get("city")),
        "sublocation": _clean_text(values.get("sublocation")),
    }
    if enrichment is None:
        return merged
    online = enrichment.as_location_dict()
    for field in ("country", "state", "city", "sublocation"):
        if not merged.get(field):
            merged[field] = _clean_text(online.get(field))
    return merged


class NominatimReverseGeocoder:
    """Single-picture, user-triggered Nominatim reverse geocoder with local cache."""

    def __init__(
        self,
        catalog,
        endpoint: str = DEFAULT_NOMINATIM_ENDPOINT,
        user_agent: str = "MyPicsDB3/unknown",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener: Optional[Callable[..., Any]] = None,
        clock: Optional[Callable[[], float]] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        min_request_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ):
        self.catalog = catalog
        self.endpoint = normalize_nominatim_endpoint(endpoint)
        self.user_agent = str(user_agent or "MyPicsDB3/unknown").strip()
        self.timeout_seconds = max(1, min(30, int(timeout_seconds)))
        self.opener = opener or urlopen
        self.clock = clock or time.time
        self.sleeper = sleeper or time.sleep
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))

    def _cached(self, latitude: float, longitude: float) -> Optional[ResolvedLocation]:
        raw = self.catalog.meta_value(_cache_key(self.endpoint, latitude, longitude))
        if not raw:
            return None
        return _result_from_json(raw)

    def _respect_rate_limit(self) -> None:
        """Serialize cache misses to at most one request per configured interval.

        The normal Kodi route also holds the catalogue-wide location-enrichment
        lock. Persisting the timestamp in ``meta`` makes the public-service
        courtesy interval survive add-on/service restarts as well.
        """
        if self.min_request_interval_seconds <= 0:
            return
        key = _rate_limit_key(self.endpoint)
        try:
            last = float(self.catalog.meta_value(key) or 0.0)
        except (TypeError, ValueError):
            last = 0.0
        now = float(self.clock())
        wait = self.min_request_interval_seconds - (now - last)
        if last > 0.0 and wait > 0.0:
            self.sleeper(wait)
            now = float(self.clock())
        # Record the attempt before network I/O so repeated failures cannot
        # accidentally hammer a shared endpoint.
        self.catalog.set_meta_value(key, "%.6f" % now)

    def resolve(self, latitude: float, longitude: float) -> ResolvedLocation:
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            raise ReverseGeocodingError("GPS coordinates are outside the valid range")

        cached = self._cached(latitude, longitude)
        if cached is not None:
            return cached

        self._respect_rate_limit()

        query = urlencode(
            {
                "format": "geocodejson",
                "lat": "%.7f" % latitude,
                "lon": "%.7f" % longitude,
                "addressdetails": "1",
                "layer": "address",
            }
        )
        request = Request(
            "%s/reverse?%s" % (self.endpoint, query),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            response = self.opener(request, timeout=self.timeout_seconds)
            try:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            raise ReverseGeocodingError("Reverse geocoding request failed: %s" % exc) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ReverseGeocodingError("Reverse geocoding response was unexpectedly large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ReverseGeocodingError("Reverse geocoding returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ReverseGeocodingError("Reverse geocoding returned an invalid response")
        result = parse_nominatim_geocodejson(payload)
        self.catalog.set_meta_value(_cache_key(self.endpoint, latitude, longitude), _result_to_json(result))
        return result
