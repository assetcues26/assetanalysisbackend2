#!/usr/bin/env python3
"""End-to-end: upload photo -> storage -> AI analysis -> activity event."""

from __future__ import annotations

import base64
import os
import sys
import time

import httpx

API_BASE = os.environ.get("E2E_API_BASE", "http://127.0.0.1:8000").rstrip("/")
POLL_SECONDS = 90
POLL_INTERVAL = 2.0

# Minimal valid 1x1 JPEG
MINIMAL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDABALDA4MChAODQ4SERATGCgaGBoWGDEjJR0oOjM9PDkz"
    "ODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/wAARCAABAAEDASIAAhEBAxEB/8QAFQAB"
    "AQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAA"
    "AAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k="
)


def test_image_bytes(client: httpx.Client) -> bytes:
    """Prefer a real stored asset image so Tagging AI accepts the upload."""
    for query in ("AST-10004", "AST-10001"):
        listed = client.get("/v1/saas/assets", params={"q": query, "limit": 1}).json()
        items = listed.get("items") or []
        if not items:
            continue
        url = items[0].get("asset_image_url")
        if not url:
            continue
        img = httpx.get(url, timeout=30.0)
        if img.status_code == 200 and len(img.content) > 100:
            return img.content
    return MINIMAL_JPEG


def headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    key = os.environ.get("DEMO_API_KEY", "").strip()
    if key:
        h["X-Demo-Key"] = key
    return h


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def main() -> None:
    client = httpx.Client(base_url=API_BASE, timeout=120.0, headers=headers())

    # 1. OpenAPI exposes image upload route
    openapi = client.get("/openapi.json").json()
    path = "/v1/saas/assets/{asset_id}/images"
    if path not in openapi.get("paths", {}):
        fail(f"OpenAPI missing {path}")
    ok(f"OpenAPI has {path}")

    # 2. Pick pending asset without image
    listed = client.get("/v1/saas/assets", params={"ai_status": "pending", "limit": 20}).json()
    candidates = [
        a for a in listed.get("items", []) if not a.get("asset_image_url")
    ]
    if not candidates:
        fail("No pending asset without image (expected AST-10003/10005/10006)")
    asset = candidates[0]
    asset_id = asset["id"]
    asset_label = asset.get("assetid") or asset_id
    ok(f"Using {asset_label} ({asset_id})")

    image_bytes = test_image_bytes(client)

    # 3. POST image
    upload = client.post(
        f"/v1/saas/assets/{asset_id}/images",
        files={"assetimage": ("demo.jpg", image_bytes, "image/jpeg")},
    )
    if upload.status_code != 200:
        fail(f"Upload HTTP {upload.status_code}: {upload.text[:500]}")
    body = upload.json()
    uploaded = body.get("asset") or {}
    if not uploaded.get("asset_image_url"):
        fail("API response missing asset_image_url after upload")
    if uploaded.get("ai_status") != "analyzing":
        fail(f"Expected ai_status=analyzing, got {uploaded.get('ai_status')}")
    ok("Upload returned asset_image_url and ai_status=analyzing")

    # 4. Poll until analysis completes
    deadline = time.time() + POLL_SECONDS
    final_status = None
    while time.time() < deadline:
        detail = client.get(f"/v1/saas/assets/{asset_id}").json()
        status = (detail.get("asset") or {}).get("ai_status")
        if status in ("pass", "fail", "error"):
            final_status = status
            break
        time.sleep(POLL_INTERVAL)

    if final_status is None:
        fail(f"AI analysis did not finish within {POLL_SECONDS}s")
    if final_status == "error":
        latest = (detail.get("latest_analysis") or {}).get("failure_summary") or {}
        fail(f"AI status error: {latest.get('error') or latest}")
    ok(f"AI analysis finished with status={final_status}")

    # 5. Activity event photos_uploaded
    activity = client.get("/v1/saas/activity", params={"limit": 30}).json()
    events = [
        e
        for e in activity.get("items", [])
        if e.get("event_type") == "photos_uploaded" and e.get("asset_id") == asset_id
    ]
    if not events:
        fail("No photos_uploaded activity event for asset")
    ok("photos_uploaded activity event logged")

    print(f"\nE2E PASS for {asset_label} — ai_status={final_status}")


if __name__ == "__main__":
    main()
