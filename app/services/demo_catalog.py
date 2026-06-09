"""Load hardcoded demo asset catalog for V6 ERP flow."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.services.catalog_far import enrich_catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_catalog.json"


@lru_cache
def load_demo_catalog() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("demo_catalog.json must be a JSON array")
    return enrich_catalog(data)


def get_catalog_item(catalog_id: str) -> dict | None:
    for item in load_demo_catalog():
        if item.get("catalog_id") == catalog_id:
            return item
    return None
