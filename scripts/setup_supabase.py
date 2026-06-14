"""Apply Supabase migrations and create storage buckets via direct Postgres."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "supabase" / "migrations" / "001_analyses.sql",
    ROOT / "supabase" / "migrations" / "002_capture_sessions.sql",
    ROOT / "supabase" / "migrations" / "003_capture_sessions_market_region.sql",
    ROOT / "supabase" / "migrations" / "004_saas_assets.sql",
    ROOT / "supabase" / "migrations" / "005_saas_public_tables.sql",
    ROOT / "supabase" / "migrations" / "006_saas_extended.sql",
]

BUCKET_SQL = """
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('analysis-images', 'analysis-images', false, 20971520, ARRAY['image/jpeg','image/png','image/webp']::text[]),
  ('capture-images', 'capture-images', false, 20971520, ARRAY['image/jpeg','image/png','image/webp']::text[]),
  ('saas-asset-images', 'saas-asset-images', false, 20971520, ARRAY['image/jpeg','image/png','image/webp']::text[])
ON CONFLICT (id) DO UPDATE SET
  public = EXCLUDED.public,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;
"""


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else None
    if not password:
        print("Usage: python setup_supabase.py <postgres-password>")
        return 1

    conn = psycopg2.connect(
        host="db.byftlfblysvlmqpcqfnu.supabase.co",
        port=5432,
        dbname="postgres",
        user="postgres",
        password=password,
        sslmode="require",
    )
    conn.autocommit = True
    cur = conn.cursor()

    for path in MIGRATIONS:
        sql = path.read_text(encoding="utf-8")
        print(f"Applying {path.name}...")
        cur.execute(sql)
        print(f"  OK: {path.name}")

    print("Creating storage buckets...")
    cur.execute(BUCKET_SQL)
    print("  OK: buckets")

    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    print("Public tables:", [r[0] for r in cur.fetchall()])
    cur.execute("SELECT id, public FROM storage.buckets ORDER BY id")
    print("Storage buckets:", cur.fetchall())

    cur.close()
    conn.close()
    print("Supabase setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
