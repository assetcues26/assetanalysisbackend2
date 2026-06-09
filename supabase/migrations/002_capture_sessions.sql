-- Cross-device capture sessions (demo user_id = 100)
-- Run in Supabase SQL Editor after 001_analyses.sql

CREATE TABLE IF NOT EXISTS capture_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token   TEXT NOT NULL UNIQUE,
  user_id         INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'analyzing', 'completed', 'expired')),
  processing_mode TEXT NOT NULL DEFAULT 'direct'
                  CHECK (processing_mode IN ('collage', 'direct')),
  image_count     INTEGER NOT NULL DEFAULT 0 CHECK (image_count >= 0),
  entry_id        TEXT,
  expires_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS capture_session_images (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id    UUID NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
  user_id       INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  sort_order    INTEGER NOT NULL CHECK (sort_order >= 1),
  storage_path  TEXT NOT NULL UNIQUE,
  source        TEXT NOT NULL DEFAULT 'mobile' CHECK (source IN ('laptop', 'mobile')),
  file_name     TEXT,
  mime_type     TEXT NOT NULL DEFAULT 'image/jpeg',
  byte_size     INTEGER,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_token ON capture_sessions (session_token);
CREATE INDEX IF NOT EXISTS idx_capture_sessions_status_expires ON capture_sessions (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_capture_session_images_session ON capture_session_images (session_id, sort_order);

DROP TRIGGER IF EXISTS capture_sessions_updated_at ON capture_sessions;
CREATE TRIGGER capture_sessions_updated_at
  BEFORE UPDATE ON capture_sessions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE capture_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE capture_session_images ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS capture_sessions_demo_all ON capture_sessions;
CREATE POLICY capture_sessions_demo_all ON capture_sessions
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

DROP POLICY IF EXISTS capture_session_images_demo_all ON capture_session_images;
CREATE POLICY capture_session_images_demo_all ON capture_session_images
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

-- Storage bucket: create "capture-images" as PRIVATE in Supabase Dashboard
-- Path: user_100/sessions/{session_id}/upload_NN.jpg
