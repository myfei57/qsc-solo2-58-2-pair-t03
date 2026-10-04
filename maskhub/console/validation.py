"""Request field helpers used by the handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maskhub.errors import InvalidRequest


def require_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest(f"{key} is required")
    return value.strip()


def optional_text(payload: Mapping[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise InvalidRequest(f"{key} must be a string")
    return value.strip()


def require_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise InvalidRequest(f"{key} must be a boolean")
    return value


def require_int(payload: Mapping[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequest(f"{key} must be an integer")
    return value


def require_text_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise InvalidRequest(f"{key} must be a non-empty list")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequest(f"{key} entries must be non-empty strings")
        items.append(item.strip())
    return items
