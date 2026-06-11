-- Store laptop-selected market region on cross-device capture sessions

ALTER TABLE capture_sessions
  ADD COLUMN IF NOT EXISTS market_region TEXT NOT NULL DEFAULT 'IN'
  CHECK (market_region IN ('IN', 'US', 'GB'));
