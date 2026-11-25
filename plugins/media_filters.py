"""Pure predicates for user-configured file-name and size exclusions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _items(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = values.split("|")
    if not isinstance(values, Iterable):
        values = (values,)
    return tuple(str(value).strip() for value in values if str(value).strip())


def keyword_filter(keywords: Any, file_name: str | None) -> bool:
    """Return True when a filename contains a configured excluded keyword."""
    name = (file_name or "").casefold()
    return bool(name) and any(keyword.casefold() in name for keyword in _items(keywords))


def extension_filter(extensions: Any, file_name: str | None) -> bool:
    """Return True when the filename's final extension is excluded."""
    name = (file_name or "").casefold().rstrip(".")
    suffix = name.rsplit(".", 1)[1] if "." in name else ""
    if not suffix:
        return False
    excluded = {value.casefold().lstrip(".") for value in _items(extensions)}
    return suffix in excluded


def size_filter(max_size: Any, min_size: Any, file_size: Any) -> bool:
    """Return True when a file size in bytes falls outside configured MB bounds."""
    try:
        size_mb = float(file_size) / (1024 * 1024)
        minimum = max(0.0, float(min_size or 0))
        maximum = max(0.0, float(max_size or 0))
    except (TypeError, ValueError):
        return False
    return (minimum > 0 and size_mb < minimum) or (maximum > 0 and size_mb > maximum)
