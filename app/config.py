"""Application configuration."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SUPPORTED_MARKET_REGIONS = frozenset({"IN", "US", "GB"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_thinking_enabled: bool = False
    gemini_thinking_budget: int = 2048
    min_images: int = 1
    max_images: int = 10
    max_image_size_mb: int = 15
    max_session_upload_total_mb: int = 15
    max_preprocess_edge_px: int = 2048
    max_gemini_payload_mb: int = 18
    gemini_analyze_temperature: float = 0.0
    gemini_max_output_tokens: int = 8192

    # Detail vs cost lever (SDK supports low/medium/high; ultra_high not available -> clamps to high)
    media_resolution_collage: str = "high"
    media_resolution_multi: str = "high"

    # Pricing for cost estimates (USD per 1M tokens); override per deployed model
    gemini_input_usd_per_1m: float = 0.25
    gemini_output_usd_per_1m: float = 1.50

    # USD->INR. Production: FX_ENABLED=true (live rate + fallback). Dev can use fixed rate.
    fx_enabled: bool = True
    fx_api_url: str = "https://api.frankfurter.dev/v1/latest"
    fx_cache_ttl_seconds: int = 3600
    fx_timeout_seconds: float = 4.0
    usd_to_inr_fallback: float = 83.0
    usd_to_gbp_fallback: float = 0.79

    # Valuation tables (JSON). Override path to hot-swap without redeploying code.
    reference_prices_path: str = ""

    # Multi-market valuation (IN / US / GB). Set false for instant rollback to India-only.
    multi_market_enabled: bool = True

    rate_limit_per_minute: int = 60
    gemini_max_retries: int = 2
    # 0 = no hard cap on Gemini call duration (wait_for disabled)
    gemini_timeout_seconds: int = 30
    # Keep below Vercel's 60s function cap so failures return cleanly
    # instead of the platform killing the request mid-flight.
    gemini_hard_timeout_seconds: int = 45

    # 0 = do not log slow-request warnings against a target
    analysis_target_ms: int = 0
    # Must match max_images for collage/multi — all uploaded angles are processed (no 6-image cap).
    max_images_latency_mode: int = 10

    review_confidence_threshold: float = 0.65
    field_confidence_threshold: float = 0.5
    valuation_confidence_threshold: float = 0.75

    prompt_version: str = "v2"

    # V6 ERP demo endpoints (/v6/demo/*). Off by default — no hardcoded catalog exposed.
    v6_demo_enabled: bool = False

    # Supabase persistence (service role — backend only, never expose to frontend)
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "analysis-images"
    supabase_signed_url_ttl_seconds: int = 3600
    supabase_persist_enabled: bool = False
    demo_user_id: int = 100
    # Optional shared secret for /v1/history* routes (empty = no guard)
    demo_api_key: str = ""
    history_rate_limit_per_minute: int = 120

    # Cross-device capture sessions (requires Supabase)
    capture_session_enabled: bool = False
    capture_session_ttl_hours: int = 2
    capture_session_analyze_stale_seconds: int = 90
    capture_storage_bucket: str = "capture-images"
    session_rate_limit_per_minute: int = 120
    frontend_base_url: str = ""

    # SaaS asset register module (isolated schema + Tagging AI proxy)
    saas_assets_enabled: bool = False
    saas_assets_storage_bucket: str = "saas-asset-images"
    saas_asset_create_session_ttl_minutes: int = 30
    saas_assets_rate_limit_per_minute: int = 120
    tagging_ai_api_url: str = "https://taggingai.vercel.app/api/asset_analysis"
    tagging_ai_timeout_seconds: int = 90

    # Client defaults (override via env without code changes)
    default_locale: str = "en-IN"
    market_region: str = "IN"  # MARKET_REGION=IN|US|GB
    display_currency: str = "INR"

    @field_validator("market_region")
    @classmethod
    def _normalize_market_region(cls, value: str) -> str:
        raw = (value or "IN").strip().upper()
        return raw if raw in _SUPPORTED_MARKET_REGIONS else "IN"

    allowed_mime_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )

    @property
    def max_image_size_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024

    @property
    def max_session_upload_total_bytes(self) -> int:
        return self.max_session_upload_total_mb * 1024 * 1024

    @property
    def max_gemini_payload_bytes(self) -> int:
        """Total inline payload budget for a single Gemini API call."""
        return self.max_gemini_payload_mb * 1024 * 1024

    @property
    def upload_image_limit(self) -> int:
        """Max images per analyze request (collage + multi). Uses full max_images batch."""
        return self.max_images

    @property
    def max_multipart_part_bytes(self) -> int:
        """Per-part cap for multipart uploads (well above per-file image limit)."""
        return max(self.max_image_size_bytes * 2, 32 * 1024 * 1024)

    def max_preprocess_edge_for_count(self, image_count: int) -> int:
        """Adaptive resize to stay within the 10s server budget."""
        if image_count <= 1:
            return min(self.max_preprocess_edge_px, 2048)
        if image_count <= 5:
            return min(self.max_preprocess_edge_px, 1280)
        return min(self.max_preprocess_edge_px, 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
