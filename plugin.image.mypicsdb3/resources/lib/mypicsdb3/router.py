from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
from urllib.parse import parse_qs, unquote, urlparse


@dataclass(frozen=True)
class Request:
    route: str
    params: Dict[str, str]


def parse_request(url: str, query: str = "") -> Request:
    parsed = urlparse(url)
    route = parsed.path.strip("/")
    raw_query = query.lstrip("?") or parsed.query
    parsed_params = parse_qs(raw_query, keep_blank_values=True)
    params = {key: unquote(values[-1]) for key, values in parsed_params.items() if values}
    return Request(route=route, params=params)
