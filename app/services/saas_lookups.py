"""Static master data lookups for SaaS asset register."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOOKUPS_PATH = Path(__file__).resolve().parents[1] / "data" / "saas_lookups.json"

VALID_TYPES = frozenset({"assetclass", "category", "subcategory", "makemodel", "company"})


@lru_cache(maxsize=1)
def _load_lookups() -> dict[str, list[dict[str, Any]]]:
    with _LOOKUPS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_lookups(
    lookup_type: str,
    *,
    parent_id: str | None = None,
) -> list[dict[str, Any]]:
    if lookup_type not in VALID_TYPES:
        raise ValueError(f"Invalid lookup type: {lookup_type}")

    items = list(_load_lookups().get(lookup_type, []))
    if not parent_id:
        return items

    parent_key = {
        "category": "assetclassid",
        "subcategory": "categoryid",
        "makemodel": "subcategoryid",
    }.get(lookup_type)
    if not parent_key:
        return items
    return [i for i in items if str(i.get(parent_key) or "") == parent_id]
