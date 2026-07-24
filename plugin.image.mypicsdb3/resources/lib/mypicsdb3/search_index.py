from __future__ import annotations

import unicodedata
from typing import Any, Iterable, List, Mapping, Sequence, Tuple


MAX_SEARCH_QUERY_LENGTH = 512
MAX_SEARCH_QUERY_TOKENS = 12
MAX_SEARCH_TOKEN_LENGTH = 191
MAX_SEARCH_DOCUMENT_TOKENS = 256
MAX_SEARCH_DOCUMENT_BYTES = 60000
MAX_INDEX_VALUE_LENGTH = 65535


class SearchTextError(ValueError):
    """Raised when a global-search string cannot be normalized safely."""


def _normalized_text(value: Any, maximum: int) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    if len(text) > maximum:
        text = text[:maximum]
    return unicodedata.normalize("NFKC", text.casefold())


def _tokenize(value: Any, *, strict_token_length: bool, maximum_text_length: int) -> Tuple[str, ...]:
    normalized = _normalized_text(value, maximum_text_length)
    tokens: List[str] = []
    current: List[str] = []

    def flush() -> None:
        if not current:
            return
        token = "".join(current)
        current.clear()
        if len(token) > MAX_SEARCH_TOKEN_LENGTH:
            if strict_token_length:
                raise SearchTextError(
                    "Search words may contain at most %d characters"
                    % MAX_SEARCH_TOKEN_LENGTH
                )
            token = token[:MAX_SEARCH_TOKEN_LENGTH]
        if token:
            tokens.append(token)

    for character in normalized:
        if character.isalnum():
            current.append(character)
        else:
            flush()
    flush()
    return tuple(tokens)


def normalize_search_query(value: Any) -> Tuple[str, Tuple[str, ...]]:
    """Return canonical AND-search text and Unicode-normalized tokens.

    Query words use NFKC normalization and Unicode ``casefold``. Punctuation and
    path separators become token boundaries. Repeated words are removed while
    preserving their first occurrence.
    """
    if not isinstance(value, str):
        raise SearchTextError("Search text must be a string")
    if len(value) > MAX_SEARCH_QUERY_LENGTH:
        raise SearchTextError(
            "Search text may contain at most %d characters"
            % MAX_SEARCH_QUERY_LENGTH
        )
    raw_tokens = _tokenize(
        value,
        strict_token_length=True,
        maximum_text_length=MAX_SEARCH_QUERY_LENGTH,
    )
    unique: List[str] = []
    seen = set()
    for token in raw_tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    if not unique:
        raise SearchTextError("Enter one or more letters or numbers")
    if len(unique) > MAX_SEARCH_QUERY_TOKENS:
        raise SearchTextError(
            "Search text may contain at most %d different words"
            % MAX_SEARCH_QUERY_TOKENS
        )
    tokens = tuple(unique)
    return " ".join(tokens), tokens


def _field_tokens(values: Sequence[Any]) -> Tuple[str, ...]:
    tokens = set()
    for value in values:
        tokens.update(
            _tokenize(
                value,
                strict_token_length=False,
                maximum_text_length=MAX_INDEX_VALUE_LENGTH,
            )
        )
    return tuple(sorted(tokens))


def build_picture_search_document(
    record: Mapping[str, Any],
    keywords: Iterable[Any] = (),
) -> str:
    """Build one compact normalized token document for a picture.

    Field order favours the terms users most often remember. The document is
    padded with spaces so exact token membership can be expressed with a
    backend-neutral ``LIKE '% token %'`` predicate without FTS/FULLTEXT.
    """
    fields = (
        (record.get("filename"),),
        tuple(keywords),
        (record.get("caption"),),
        (record.get("uri"),),
        (record.get("camera_make"), record.get("camera_model")),
        (
            record.get("city"),
            record.get("state"),
            record.get("country"),
            record.get("sublocation"),
        ),
    )
    ordered: List[str] = []
    seen = set()
    document_bytes = 2  # Leading and trailing spaces.
    for values in fields:
        for token in _field_tokens(values):
            if token in seen:
                continue
            encoded_size = len(token.encode("utf-8")) + 1
            if document_bytes + encoded_size > MAX_SEARCH_DOCUMENT_BYTES:
                continue
            seen.add(token)
            ordered.append(token)
            document_bytes += encoded_size
            if len(ordered) >= MAX_SEARCH_DOCUMENT_TOKENS:
                break
        if len(ordered) >= MAX_SEARCH_DOCUMENT_TOKENS:
            break
    return " " + " ".join(ordered) + " "
