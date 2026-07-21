"""Pydantic helpers: coerce LLM quirks (stringified JSON lists/dicts)."""

from __future__ import annotations

import json
from typing import Any


def coerce_json_list(value: Any) -> Any:
    """If model returns a JSON array as a string, parse it into a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 容错：截取首个 [...] 片段
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return value
        else:
            return value
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("rows", "items", "fields", "evidence_refs"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return value


def coerce_json_dict(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return value
        else:
            return value
    return parsed if isinstance(parsed, dict) else value
