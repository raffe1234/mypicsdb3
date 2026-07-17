from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode, urlsplit, urlunsplit


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def local_datetime_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_text(payload)


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: Any, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def split_csv(value: str) -> Tuple[str, ...]:
    items = []
    for item in (value or "").split(","):
        item = item.strip().lower().lstrip(".")
        if item and item not in items:
            items.append(item)
    return tuple(items)


def split_pipe(value: str) -> Tuple[str, ...]:
    return tuple(item.strip().lower() for item in (value or "").split("|") if item.strip())


def normalize_uri(uri: str, directory: bool = False) -> str:
    value = (uri or "").strip().replace("\\", "/")
    if not value:
        return value
    is_windows_drive = bool(re.match(r"^[A-Za-z]:/", value))
    parts = urlsplit(value)
    if parts.scheme and not is_windows_drive:
        path = re.sub(r"/{2,}", "/", parts.path)
        value = urlunsplit((parts.scheme.lower(), parts.netloc, path, parts.query, parts.fragment))
    else:
        value = os.path.normpath(value).replace("\\", "/")
    if directory:
        value = value.rstrip("/") + "/"
    return value


def join_uri(base: str, name: str, directory: bool = False) -> str:
    clean_name = name.replace("\\", "/").strip("/")
    if "://" in base or base.startswith("special://"):
        result = base.rstrip("/") + "/" + clean_name
    else:
        result = os.path.join(base, name).replace("\\", "/")
    return normalize_uri(result, directory=directory)


def basename_uri(uri: str) -> str:
    return uri.rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]


def parent_uri(uri: str) -> str:
    value = uri.rstrip("/").replace("\\", "/")
    if "/" not in value:
        return ""
    parent = value.rsplit("/", 1)[0]
    if parent.endswith(":"):
        parent += "/"
    return normalize_uri(parent, directory=True)


def extension_of(name: str) -> str:
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def plugin_url(base_url: str, route: str, **params: Any) -> str:
    route = route.strip("/")
    parts = urlsplit(base_url)
    if parts.scheme and parts.netloc:
        plugin_root = urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
    else:
        plugin_root = base_url.split("?", 1)[0].rstrip("/")
    url = plugin_root + "/" + route if route else plugin_root + "/"
    clean = {key: str(value) for key, value in params.items() if value is not None and value != ""}
    return url + ("?" + urlencode(clean, doseq=True) if clean else "")


def safe_limit(value: Any, default: int, maximum: int = 500) -> int:
    return parse_int(value, default, minimum=1, maximum=maximum)


def chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def decode_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16-le", "latin-1"):
            try:
                return value.decode(encoding).strip("\x00 ")
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", "replace").strip("\x00 ")
    return str(value).strip()


def unique_strings(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = decode_text(value)
        if not text:
            continue
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result
