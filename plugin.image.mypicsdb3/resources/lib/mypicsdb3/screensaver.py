from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .config import Settings, from_getter
from .db.engine import DatabaseEngine
from .query_model import compile_picture_query
from .rating_policy import RATING_POLICY_ALL, normalize_rating_policy, rating_sql_predicate
from .saved_searches import parse_stored_saved_search


SCREEN_SOURCE_MANUAL = "manual"
SCREEN_SOURCE_SMART = "smart"
SCREEN_SOURCE_TYPES = frozenset((SCREEN_SOURCE_MANUAL, SCREEN_SOURCE_SMART))
MAX_SCREENSAVER_ITEMS = 1000
DEFAULT_SCREENSAVER_ITEMS = 250
DEFAULT_SLIDE_SECONDS = 8


class ScreensaverSourceError(RuntimeError):
    """Raised when a configured screensaver source cannot be read safely."""


@dataclass(frozen=True)
class ScreensaverSource:
    source_type: str
    source_id: int
    name: str


@dataclass(frozen=True)
class ScreensaverPicture:
    id: int
    uri: str
    filename: str


def normalize_source_type(value: Any) -> str:
    source_type = str(value or "").strip().lower()
    if source_type not in SCREEN_SOURCE_TYPES:
        raise ScreensaverSourceError("Unknown screensaver source type")
    return source_type


def normalize_source_id(value: Any) -> int:
    try:
        source_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ScreensaverSourceError("Screensaver source ID is invalid") from exc
    if source_id <= 0:
        raise ScreensaverSourceError("Screensaver source ID is invalid")
    return source_id


def normalize_item_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SCREENSAVER_ITEMS
    return max(1, min(MAX_SCREENSAVER_ITEMS, limit))


def normalize_slide_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SLIDE_SECONDS
    return max(2, min(120, seconds))


def plugin_settings_from_addon(plugin_addon, profile_path: str) -> Settings:
    """Read the picture add-on settings without constructing KodiContext.

    The screensaver deliberately does not publish Home properties or initialize
    migrations. It only needs the same database connection and rating policy as
    the picture add-on.
    """

    return from_getter(plugin_addon.getSetting, profile_path)


class ScreensaverReadOnlyProvider:
    """Read manual/smart collection pictures without scans or schema writes."""

    def __init__(
        self,
        settings: Settings,
        logger=None,
        engine: Optional[DatabaseEngine] = None,
    ):
        self.settings = settings
        self.logger = logger
        self.engine = engine if engine is not None else DatabaseEngine(settings, logger)
        self.rating_policy = normalize_rating_policy(
            getattr(settings, "minimum_rating_policy", RATING_POLICY_ALL)
        )

    def _connect(self):
        try:
            return self.engine.connect_readonly()
        except Exception as exc:
            raise ScreensaverSourceError(
                "MyPicsDB catalogue is unavailable: %s" % exc
            ) from exc

    def list_sources(self) -> List[ScreensaverSource]:
        connection = self._connect()
        try:
            manual_order = (
                "name COLLATE NOCASE, id"
                if self.engine.backend == "sqlite"
                else "name, id"
            )
            smart_order = (
                "name COLLATE NOCASE, id"
                if self.engine.backend == "sqlite"
                else "name, id"
            )
            manual = self.engine.fetchall(
                connection,
                "SELECT id, name FROM collections ORDER BY %s" % manual_order,
            )
            smart = self.engine.fetchall(
                connection,
                "SELECT id, name FROM saved_searches ORDER BY %s" % smart_order,
            )
        except Exception as exc:
            raise ScreensaverSourceError(
                "Could not read MyPicsDB collections: %s" % exc
            ) from exc
        finally:
            connection.close()

        result = [
            ScreensaverSource(SCREEN_SOURCE_MANUAL, int(row["id"]), str(row["name"]))
            for row in manual
        ]
        result.extend(
            ScreensaverSource(SCREEN_SOURCE_SMART, int(row["id"]), str(row["name"]))
            for row in smart
        )
        return result

    def source_exists(self, source_type: str, source_id: int) -> bool:
        source_type = normalize_source_type(source_type)
        source_id = normalize_source_id(source_id)
        table = "collections" if source_type == SCREEN_SOURCE_MANUAL else "saved_searches"
        connection = self._connect()
        try:
            return self.engine.fetchone(
                connection,
                "SELECT id FROM %s WHERE id=?" % table,
                (source_id,),
            ) is not None
        except Exception as exc:
            raise ScreensaverSourceError(
                "Could not validate screensaver source: %s" % exc
            ) from exc
        finally:
            connection.close()

    @staticmethod
    def _picture_rows(rows: Sequence[Dict[str, Any]]) -> List[ScreensaverPicture]:
        result: List[ScreensaverPicture] = []
        seen = set()
        for row in rows:
            uri = str(row.get("uri") or "").strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            try:
                picture_id = int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            result.append(
                ScreensaverPicture(
                    id=picture_id,
                    uri=uri,
                    filename=str(row.get("filename") or ""),
                )
            )
        return result

    def _bounded_random_rows(
        self,
        connection,
        from_sql: str,
        where_sql: str,
        params: Sequence[Any],
        limit: int,
        seed: Optional[float],
    ) -> List[Dict[str, Any]]:
        if seed is None:
            pivot = random.random()
            rng = random.Random()
        else:
            try:
                pivot = float(seed) % 1.0
            except (TypeError, ValueError):
                pivot = 0.0
            rng = random.Random(pivot)

        select = "SELECT p.id, p.uri, p.filename, p.random_key " + from_sql
        first = self.engine.fetchall(
            connection,
            select
            + " WHERE (%s) AND COALESCE(p.random_key,0)>=? " % where_sql
            + "ORDER BY COALESCE(p.random_key,0), p.id LIMIT ?",
            (*params, pivot, limit),
        )
        if len(first) < limit:
            second = self.engine.fetchall(
                connection,
                select
                + " WHERE (%s) AND COALESCE(p.random_key,0)<? " % where_sql
                + "ORDER BY COALESCE(p.random_key,0), p.id LIMIT ?",
                (*params, pivot, limit - len(first)),
            )
            first.extend(second)
        rng.shuffle(first)
        return first

    def _manual_rows(
        self,
        connection,
        source_id: int,
        limit: int,
        randomize: bool,
        seed: Optional[float],
    ) -> List[Dict[str, Any]]:
        predicates = [
            "ci.collection_id=?",
            "p.is_missing=0",
            "p.media_type='picture'",
        ]
        params: List[Any] = [source_id]
        rating_sql, rating_params = rating_sql_predicate(
            self.rating_policy, "p.rating"
        )
        if rating_sql:
            predicates.append(rating_sql)
            params.extend(rating_params)
        where_sql = " AND ".join("(%s)" % item for item in predicates)
        from_sql = (
            "FROM collection_items ci JOIN pictures p ON p.id=ci.picture_id"
        )
        if randomize:
            return self._bounded_random_rows(
                connection, from_sql, where_sql, params, limit, seed
            )
        return self.engine.fetchall(
            connection,
            "SELECT p.id, p.uri, p.filename, p.random_key "
            + from_sql
            + " WHERE "
            + where_sql
            + " ORDER BY ci.position, ci.picture_id LIMIT ?",
            (*params, limit),
        )

    def _smart_rows(
        self,
        connection,
        source_id: int,
        limit: int,
        randomize: bool,
        seed: Optional[float],
    ) -> List[Dict[str, Any]]:
        row = self.engine.fetchone(
            connection,
            "SELECT id, name, query_version, query_json, created_at, updated_at "
            "FROM saved_searches WHERE id=?",
            (source_id,),
        )
        if row is None:
            return []
        try:
            saved = parse_stored_saved_search(row)
            compiled = compile_picture_query(saved.query, self.rating_policy)
        except Exception as exc:
            raise ScreensaverSourceError(
                "Saved smart collection is invalid: %s" % exc
            ) from exc

        where_sql = "(%s) AND p.media_type='picture'" % compiled.where_sql
        from_sql = "FROM pictures p"
        if randomize:
            return self._bounded_random_rows(
                connection,
                from_sql,
                where_sql,
                compiled.params,
                limit,
                seed,
            )
        return self.engine.fetchall(
            connection,
            "SELECT p.id, p.uri, p.filename, p.random_key "
            + from_sql
            + " WHERE "
            + where_sql
            + " ORDER BY "
            + compiled.order_by_sql
            + " LIMIT ?",
            (*compiled.params, limit),
        )

    def pictures(
        self,
        source_type: str,
        source_id: int,
        limit: int = DEFAULT_SCREENSAVER_ITEMS,
        randomize: bool = True,
        seed: Optional[float] = None,
    ) -> List[ScreensaverPicture]:
        source_type = normalize_source_type(source_type)
        source_id = normalize_source_id(source_id)
        limit = normalize_item_limit(limit)
        connection = self._connect()
        try:
            table = (
                "collections"
                if source_type == SCREEN_SOURCE_MANUAL
                else "saved_searches"
            )
            exists = self.engine.fetchone(
                connection,
                "SELECT id FROM %s WHERE id=?" % table,
                (source_id,),
            )
            if exists is None:
                raise ScreensaverSourceError("Configured collection no longer exists")
            if source_type == SCREEN_SOURCE_MANUAL:
                rows = self._manual_rows(
                    connection, source_id, limit, bool(randomize), seed
                )
            else:
                rows = self._smart_rows(
                    connection, source_id, limit, bool(randomize), seed
                )
        except ScreensaverSourceError:
            raise
        except Exception as exc:
            raise ScreensaverSourceError(
                "Could not read screensaver pictures: %s" % exc
            ) from exc
        finally:
            connection.close()
        return self._picture_rows(rows)
