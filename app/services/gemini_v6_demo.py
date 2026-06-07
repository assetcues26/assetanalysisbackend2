"""Gemini client for V6 demo — ERP context + images, separate prompt."""

from __future__ import annotations

from datetime import date

from PIL import Image

from app.models.demo_context import DemoContext, infer_location_profile
from app.prompts.loader import get_analysis_v6_demo_prompt
from app.services.gemini import GeminiService, _build_image_parts, _resolve_media_resolution
from app.models.responses import LLMAnalysisResult, TokenUsage
from google.genai import types


_CLIMATE_NOTES = {
    "coastal_humid": (
        "Coastal humid site — expect salt-air corrosion on outdoor metal, faster rust on "
        "HVAC condensers, generators, and vehicle underbody; monsoon moisture on enclosures."
    ),
    "dry_hot_dust": (
        "Dry hot / dusty inland — heat fading, dust in vents/filters, paint chalking; "
        "less salt rust but more particulate wear."
    ),
    "humid_inland": (
        "Humid inland — elevated moisture without constant salt spray; mold in poorly "
        "ventilated cabinets, moderate metal corrosion risk."
    ),
    "moderate": (
        "Moderate urban climate — standard tier-1/tier-2 wear; no extreme coastal or desert bias."
    ),
}


def _years_since(acquisition: date, today: date | None = None) -> float:
    today = today or date.today()
    return max(0.0, (today - acquisition).days / 365.25)


def build_demo_context_block(ctx: DemoContext) -> str:
    profile = infer_location_profile(ctx.location)
    climate = _CLIMATE_NOTES.get(profile, _CLIMATE_NOTES["moderate"])
    age_years = _years_since(ctx.acquisition_date)
    tag_line = ctx.asset_tag_number or "(not provided — read from images if visible)"
    return (
        "\n\n=== INJECTED ERP DEMO CONTEXT (GROUND TRUTH) ===\n"
        f"catalog_id: {ctx.catalog_id}\n"
        f"asset_name: {ctx.asset_name}\n"
        f"description: {ctx.description}\n"
        f"make: {ctx.make}\n"
        f"model: {ctx.model}\n"
        f"category: {ctx.category}\n"
        f"subcategory: {ctx.subcategory}\n"
        f"acquisition_date: {ctx.acquisition_date.isoformat()}\n"
        f"asset_age_years_approx: {age_years:.1f}\n"
        f"original_cost_inr: {ctx.original_cost_inr:,.0f}\n"
        f"book_nbv_inr: {ctx.book_nbv_inr:,.0f}\n"
        f"location: {ctx.location}\n"
        f"location_profile: {profile}\n"
        f"climate_notes: {climate}\n"
        f"asset_tag_number_erp: {tag_line}\n"
        "Use the above as authoritative for identity, age, book NBV baseline, and site climate. "
        "Images validate condition and visible identifiers only.\n"
    )


class GeminiV6DemoService(GeminiService):
    async def analyze_images_with_context(
        self,
        images: list[Image.Image],
        demo_context: DemoContext,
        media_resolution: str,
        locale: str = "en",
        image_labels: list[str] | None = None,
        total_images: int | None = None,
    ) -> tuple[LLMAnalysisResult, TokenUsage]:
        if not self.is_configured():
            raise RuntimeError("Gemini API key is not configured")
        if not images:
            raise ValueError("At least one image is required")

        prompt = get_analysis_v6_demo_prompt() + build_demo_context_block(demo_context)
        num_images = total_images or len(images)
        if num_images == 1:
            prompt += (
                "\n\nThis request has 1 image. For ALL seen_in_image fields "
                "(barcode_seen_in_image, stickers[].seen_in_image, "
                "damage_items[].seen_in_image), you MUST use 1. "
                "Never leave seen_in_image as null."
            )
        else:
            prompt += (
                f"\n\nThis request has {num_images} images numbered 1 through {num_images}. "
                "You MUST provide seen_in_image for every sticker and damage item."
            )
        if locale != "en":
            prompt += f"\n\nRespond in locale: {locale}."
        prompt += (
            "\n\nCLIENT MARKET: India. All valuation reasoning in INR (₹). "
            "Book NBV from ERP is the accounting baseline — as-is market value may differ based on visible condition."
        )

        parts = _build_image_parts(images, prompt, image_labels)
        config_kwargs: dict = {
            "response_mime_type": "application/json",
            "response_schema": LLMAnalysisResult,
            "temperature": self.settings.gemini_analyze_temperature,
            "max_output_tokens": self.settings.gemini_max_output_tokens,
            "media_resolution": _resolve_media_resolution(media_resolution),
        }
        if self.settings.gemini_thinking_enabled and self._model_supports_thinking():
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.settings.gemini_thinking_budget,
            )
        config = types.GenerateContentConfig(**config_kwargs)
        return await self._generate(
            parts, config, images_sent=len(images), media_resolution=media_resolution
        )
