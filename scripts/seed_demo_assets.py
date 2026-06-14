"""Seed demo SaaS assets without images (pending until photos uploaded)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.saas_assets_repository import get_saas_assets_repository

DEMO_ASSETS = [
    {
        "assetname": "HP Laptop",
        "description": "Business laptop — photos pending upload",
        "assetclassid": "IT",
        "assetclassname": "IT Equipment",
        "categoryid": "cat-laptop",
        "categoryname": "Laptops",
        "subcategoryid": "sub-laptop-biz",
        "subcategoryname": "Business Laptop",
        "makemodelid": "mm-hp-elite",
        "makemodelname": "HP EliteBook 840",
        "tagnumber": "TAG-HP-LAP-001",
        "assetnumber": "FAR-HP-LAP-001",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "85000",
        "acquisitiondate": "15-03-2024",
    },
    {
        "assetname": "HP Printer",
        "description": "Office laser printer — photos pending upload",
        "assetclassid": "OFF",
        "assetclassname": "Office Equipment",
        "categoryid": "cat-printer",
        "categoryname": "Printers",
        "subcategoryid": "sub-laser",
        "subcategoryname": "Laser Printer",
        "makemodelid": "mm-hp-lj",
        "makemodelname": "HP LaserJet Pro M404",
        "tagnumber": "TAG-HP-PRT-002",
        "assetnumber": "FAR-HP-PRT-002",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "22000",
        "acquisitiondate": "10-06-2023",
    },
    {
        "assetname": "Macbook Pro",
        "description": "Apple MacBook Pro — photos pending upload",
        "assetclassid": "IT",
        "assetclassname": "IT Equipment",
        "categoryid": "cat-laptop",
        "categoryname": "Laptops",
        "subcategoryid": "sub-laptop-mac",
        "subcategoryname": "MacBook",
        "makemodelid": "mm-mac-pro",
        "makemodelname": 'Apple MacBook Pro 14"',
        "tagnumber": "TAG-MAC-003",
        "assetnumber": "FAR-MAC-003",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "185000",
        "acquisitiondate": "01-09-2024",
    },
    {
        "assetname": "Micromax Split AC",
        "description": "Split air conditioner — photos pending upload",
        "assetclassid": "HVAC",
        "assetclassname": "HVAC & Cooling",
        "categoryid": "cat-ac",
        "categoryname": "Air Conditioning",
        "subcategoryid": "sub-split-ac",
        "subcategoryname": "Split AC",
        "makemodelid": "mm-micromax-ac",
        "makemodelname": "Micromax Split AC 1.5T",
        "tagnumber": "TAG-AC-004",
        "assetnumber": "FAR-AC-004",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "42000",
        "acquisitiondate": "20-04-2022",
    },
    {
        "assetname": "Nexon Car",
        "description": "Company vehicle — photos pending upload",
        "assetclassid": "VEH",
        "assetclassname": "Vehicles",
        "categoryid": "cat-car",
        "categoryname": "Cars & SUVs",
        "subcategoryid": "sub-suv",
        "subcategoryname": "SUV",
        "makemodelid": "mm-tata-nexon",
        "makemodelname": "Tata Nexon",
        "tagnumber": "TAG-CAR-005",
        "assetnumber": "FAR-CAR-005",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "1250000",
        "acquisitiondate": "05-11-2023",
    },
    {
        "assetname": "Rack",
        "description": "Server rack — photos pending upload",
        "assetclassid": "IT",
        "assetclassname": "IT Equipment",
        "categoryid": "cat-server",
        "categoryname": "Servers",
        "subcategoryid": "sub-server-rack",
        "subcategoryname": "Rack Server",
        "makemodelid": "mm-dell-rack",
        "makemodelname": "Dell PowerEdge Rack",
        "tagnumber": "TAG-RACK-006",
        "assetnumber": "FAR-RACK-006",
        "companyid": "3000",
        "company": "AssetCues Demo Corp",
        "customerid": "10001",
        "cost": "350000",
        "acquisitiondate": "12-01-2021",
    },
]


async def main() -> None:
    settings = get_settings()
    repo = get_saas_assets_repository(settings)
    if not repo.enabled:
        print("SaaS assets repository is not configured.")
        sys.exit(1)

    user_id = settings.demo_user_id
    existing, _ = await repo.list_assets(user_id, limit=200)
    existing_names = {str(a.assetname or "").strip().lower() for a in existing}

    created = 0
    skipped = 0
    for meta in DEMO_ASSETS:
        name_key = meta["assetname"].strip().lower()
        if name_key in existing_names:
            print(f"Skip (exists): {meta['assetname']}")
            skipped += 1
            continue
        result = await repo.register_asset(user_id, meta)
        print(f"Created {result.assetid} — {meta['assetname']} [{result.ai_status}]")
        created += 1
        existing_names.add(name_key)

    print(f"\nDone: {created} created, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(main())
