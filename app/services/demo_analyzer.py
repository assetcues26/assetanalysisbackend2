"""V6 demo analysis — ERP context + images, isolated from v1 AssetAnalysisService."""

from __future__ import annotations

import time
import uuid
from datetime import date
from typing import BinaryIO

import structlog

from app.config import Settings
from app.models.demo_context import DemoContext, infer_location_profile
from app.models.responses import (
    AnalysisPolicy,
    AnalyzeResponse,
    AssetDetails,
    DemoVerification,
    Identifiers,
    LLMAnalysisResult,
    MoneyRange,
    NbvEstimate,
    UnifiedViewMethod,
    Valuation,
    ValuationStatus,
)
from app.services.field_merger import normalize_tag_number
from app.utils.age_display import format_age_years_months
from app.utils.valuation_bullets import dedupe_bullets, split_prose_to_bullets
from app.pipeline.image_utils import fit_images_to_budget
from app.pipeline.preprocess import preprocess_images
from app.services.analyzer import AssetAnalysisService
from app.services.cost import compute_cost
from app.services.field_merger import to_asset_details
from app.markets.registry import resolve_market
from app.services.fx import get_fx_rate, get_usd_to_inr
from app.services.gemini_v6_demo import GeminiV6DemoService
from app.services.metrics import (
    IDENTITY_LOW_CONFIDENCE,
    PROCESSING_TIME_MS,
    VALUATION_WITHHELD,
)
from app.services.nbv_engine import apply_nbv_comparison
from app.services.placement_mapper import (
    build_identifiers,
    identifiers_need_review,
    merge_sticker_sources,
    stickers_image_index_need_review,
)
from app.services.reasoning_summary import build_reasoning_summary
from app.services.reference_data import reference_data_label
from app.services.condition_mapper import damage_needs_review, stickers_need_review
from app.services.erp_validation_engine import enrich_demo_verification
from app.services.identity_validator import validate_identity
from app.services.repair_policy import build_repair_plan
from app.services.valuation_display import client_valuation
from app.services.valuation_engine import compute_valuation, resolve_segment_for_asset

logger = structlog.get_logger()
V6_PROMPT_VERSION = "v6-demo"
UploadTuple = tuple[BinaryIO, str, bytes]


def _years_since(acquisition: date) -> float:
    return max(0.0, (date.today() - acquisition).days / 365.25)


def _norm_identity(value: str | None) -> str:
    return (value or "").strip().lower()


def apply_demo_asset_identity(asset: AssetDetails, ctx: DemoContext) -> AssetDetails:
    """Apply ERP book data; name/description/tag stay from vision (LLM)."""
    if ctx.make:
        asset.brand = ctx.make
    if ctx.model:
        asset.model = ctx.model
    if ctx.category:
        asset.category = ctx.category
    if ctx.subcategory:
        asset.type = ctx.subcategory
    age = _years_since(ctx.acquisition_date)
    age_label = format_age_years_months(age)
    asset.estimated_age_years = age_label
    asset.estimated_age = f"{age_label} since acquisition ({ctx.acquisition_date.isoformat()})"
    return asset


def _money_inr_midpoint(lo: float | None, hi: float | None) -> float | None:
    if lo is None and hi is None:
        return None
    if lo is None:
        return float(hi)  # type: ignore[arg-type]
    if hi is None:
        return float(lo)
    return (float(lo) + float(hi)) / 2


_CLIMATE_DISCOUNT_PCT: dict[tuple[str, str], float] = {
    # (profile, segment) -> deduction percent (positive = lower value)
    # Research sources: Cars24/Team-BHP India, ISHRAE coastal HVAC studies
    ("coastal_humid", "vehicle"): 8.0,    # Underbody rust, softer Mumbai/Chennai used market
    ("coastal_humid", "hvac"): 10.0,      # ISHRAE: coil lifespan 5-7 yr vs 10 yr rated
    ("coastal_humid", "industrial"): 5.0, # Canopy corrosion, generator enclosure rust
    ("coastal_humid", "other"): 3.0,      # General metal/enclosed assets
    ("dry_hot_dust", "vehicle"): 3.0,     # Heat/UV paint fade; smaller than coastal effect
    ("dry_hot_dust", "hvac"): 5.0,        # Dust clogging, filter stress
    ("dry_hot_dust", "industrial"): 3.0,
    ("humid_inland", "vehicle"): 4.0,     # Moderate corrosion without constant salt
    ("humid_inland", "hvac"): 5.0,
    ("humid_inland", "industrial"): 3.0,
}

_CLIMATE_REASONS: dict[tuple[str, str], str] = {
    ("coastal_humid", "vehicle"):
        "Mumbai/coastal fleet vehicles accumulate underbody rust and salt corrosion; "
        "Cars24 and Team-BHP data show used-market pricing is consistently softer "
        "vs dry NCR/Rajasthan equivalents.",
    ("coastal_humid", "hvac"):
        "ISHRAE guidelines: outdoor HVAC condenser coils in coastal India corrode "
        "2–3× faster than in dry climates, shortening effective life from 10 years "
        "to 5-7 years and depressing resale values.",
    ("coastal_humid", "industrial"):
        "Coastal salt spray accelerates canopy and exhaust-stack rust on generators "
        "and industrial enclosures; buyers discount more than for dry-climate installs.",
    ("coastal_humid", "other"):
        "High humidity and salt air raise corrosion risk on metal components "
        "and enclosed electronics at coastal sites.",
    ("dry_hot_dust", "vehicle"):
        "Intense UV, heat cycling, and road dust in dry regions (NCR, Rajasthan) "
        "cause paint chalking and plastic fade; minor but measurable used-market impact.",
    ("dry_hot_dust", "hvac"):
        "Dust accumulation clogs evaporator fins and stresses bearings; "
        "HVAC in dry-hot sites requires more frequent servicing.",
    ("dry_hot_dust", "industrial"):
        "Abrasive dust and heat cycling in dry regions accelerate seal and "
        "filter wear on industrial machinery.",
    ("humid_inland", "vehicle"):
        "Humid inland climate (e.g. eastern/central India) causes moderate underbody "
        "corrosion without the full coastal salt-spray effect.",
    ("humid_inland", "hvac"):
        "Persistent moisture and mould risk in humid inland sites reduces "
        "HVAC component life and resale appeal.",
    ("humid_inland", "industrial"):
        "Elevated moisture without salt spray — moderate corrosion risk on "
        "exposed metal parts in industrial equipment.",
}


def apply_climate_adjustment(
    valuation: Valuation,
    ctx: DemoContext,
    segment: str,
) -> tuple[Valuation, float]:
    """Apply a deterministic climate discount to the as-is INR range.

    Returns the updated Valuation and the discount percentage applied (0 if none).
    Only applied to the as_is market estimate — Book NBV is never touched.
    """
    profile = infer_location_profile(ctx.location)
    discount_pct = _CLIMATE_DISCOUNT_PCT.get((profile, segment), 0.0)
    if discount_pct <= 0 or valuation.as_is is None:
        return valuation, 0.0

    factor = 1.0 - discount_pct / 100.0
    inr = valuation.as_is.inr
    usd = valuation.as_is.usd
    new_inr_min = round(inr.min * factor, 2) if inr.min is not None else None
    new_inr_max = round(inr.max * factor, 2) if inr.max is not None else None
    new_usd_min = round(usd.min * factor, 2) if usd and usd.min is not None else None
    new_usd_max = round(usd.max * factor, 2) if usd and usd.max is not None else None

    from app.models.responses import MoneyRange, ValuationAmount
    disp = valuation.as_is.display
    new_disp_min = round(disp.min * factor, 2) if disp.min is not None else None
    new_disp_max = round(disp.max * factor, 2) if disp.max is not None else None
    new_as_is = ValuationAmount(
        inr=MoneyRange(min=new_inr_min, max=new_inr_max),
        usd=MoneyRange(min=new_usd_min, max=new_usd_max),
        display=MoneyRange(min=new_disp_min, max=new_disp_max),
        display_currency=valuation.as_is.display_currency,
    )
    valuation = valuation.model_copy(update={"as_is": new_as_is})
    return valuation, discount_pct


def build_climate_valuation_points(
    ctx: DemoContext,
    valuation: Valuation,
    llm: LLMAnalysisResult,
    climate_discount_applied_pct: float = 0.0,
    segment: str = "other",
) -> list[str]:
    profile = infer_location_profile(ctx.location)
    location = ctx.location
    cat = f"{ctx.category} {ctx.subcategory}".lower()

    profile_labels = {
        "coastal_humid": "coastal humid (salt air, monsoon moisture)",
        "dry_hot_dust": "dry hot / dusty inland",
        "humid_inland": "humid inland",
        "moderate": "moderate urban",
    }
    climate_label = profile_labels.get(profile, profile.replace("_", " "))

    parts: list[str] = [
        f"Site: {location} — {climate_label} climate.",
    ]

    reason = _CLIMATE_REASONS.get((profile, segment))
    if reason:
        parts.append(reason)
    elif profile == "coastal_humid":
        parts.append(
            "High humidity and salt air raise corrosion risk on metal components "
            "and enclosed electronics at coastal sites."
        )
    elif profile == "dry_hot_dust":
        parts.append(
            "Dry heat and dust (typical of NCR, Rajasthan, Gujarat) stress filters, "
            "plastics, and paint — moderate downward pressure vs moderate-climate peers."
        )
    elif profile == "humid_inland":
        parts.append(
            "Humid inland conditions raise mould and condensation wear without constant salt spray."
        )
    else:
        parts.append(
            "Moderate tier-1/tier-2 climate — location adds less extreme wear than coastal or desert sites."
        )

    if climate_discount_applied_pct > 0:
        parts.append(
            f"Location-based adjustment applied: −{climate_discount_applied_pct:.0f}% to current estimate "
            f"(reduces as-is value vs a neutral inland baseline for this asset class)."
        )
    else:
        parts.append(
            "No location penalty applied for this asset class and climate profile."
        )

    as_is_mid = _money_inr_midpoint(
        valuation.as_is.inr.min, valuation.as_is.inr.max
    )
    like_mid = _money_inr_midpoint(
        valuation.like_new_reference.inr.min, valuation.like_new_reference.inr.max
    )
    if as_is_mid is not None and like_mid is not None and like_mid > 0:
        gap_pct = max(0.0, (1.0 - as_is_mid / like_mid) * 100.0)
        if gap_pct >= 5:
            parts.append(
                f"Net current estimate is ~{gap_pct:.0f}% below the like-new reference, "
                "combining photographed condition and geographic wear for this site."
            )
        else:
            parts.append(
                "Current estimate is close to like-new reference — limited visible wear "
                "for this location and asset class."
            )

    llm_note = ""
    if llm.reasoning:
        llm_note = (
            (llm.valuation_assumptions or "").strip()
            or (getattr(llm.reasoning, "valuation_deliberation_notes", None) or "").strip()
        )
    if not llm_note and llm.valuation_inputs and llm.valuation_inputs.valuation_rationale:
        llm_note = llm.valuation_inputs.valuation_rationale.strip()
    bullets = [p for p in parts if p]
    if llm_note:
        bullets.extend(split_prose_to_bullets(llm_note))
    return dedupe_bullets(bullets)


def build_demo_verification(
    ctx: DemoContext,
    llm: LLMAnalysisResult,
    identifiers: Identifiers,
) -> DemoVerification:
    erp_tag = normalize_tag_number(ctx.asset_tag_number)
    detected_norm = identifiers.asset_tag_number
    detected_raw = identifiers.asset_tag_number_raw

    if not erp_tag:
        tag_match = False
        note = "No ERP tag in input to compare."
    elif not detected_norm:
        tag_match = False
        note = "Tag not detected or unreadable in images."
    elif detected_norm == erp_tag:
        tag_match = True
        note = "Detected tag matches ERP input exactly."
    else:
        tag_match = False
        note = f"Mismatch: ERP {erp_tag} vs detected {detected_norm}."

    vision_make = (llm.brand or "").strip() or None
    vision_model = (llm.model or "").strip() or None
    make_match = (
        _norm_identity(vision_make) == _norm_identity(ctx.make) if ctx.make and vision_make else None
    )
    model_match = (
        _norm_identity(vision_model) == _norm_identity(ctx.model)
        if ctx.model and vision_model
        else None
    )

    return DemoVerification(
        erp_tag_number=erp_tag,
        detected_tag_number=detected_norm,
        detected_tag_number_raw=detected_raw,
        tag_number_match=tag_match,
        tag_match_note=note,
        erp_make=ctx.make or None,
        erp_model=ctx.model or None,
        vision_make=vision_make,
        vision_model=vision_model,
        make_match=make_match,
        model_match=model_match,
        erp_book_nbv_inr=round(float(ctx.book_nbv_inr), 2),
    )


def apply_demo_book_nbv(
    valuation: Valuation,
    book_nbv_inr: float,
    *,
    usd_to_inr: float,
    acquisition_date: date,
) -> Valuation:
    """Set NBV to the exact ERP book value (no synthetic depreciation band)."""
    nbv_inr = round(float(book_nbv_inr), 2)
    usd = round(nbv_inr / usd_to_inr, 2) if usd_to_inr else None
    valuation.nbv = NbvEstimate(
        usd=MoneyRange(min=usd, max=usd),
        inr=MoneyRange(min=nbv_inr, max=nbv_inr),
        display=MoneyRange(min=nbv_inr, max=nbv_inr),
        display_currency="INR",
        method="erp_book_nbv",
        age_years_used=_years_since(acquisition_date),
        disclaimer="Book NBV from ERP input — accounting value on the books.",
    )
    return valuation


class DemoAnalysisService:
    def __init__(self, settings: Settings, gemini: GeminiV6DemoService):
        self.settings = settings
        self.gemini = gemini

    async def analyze(
        self,
        files: list[UploadTuple],
        demo_context: DemoContext,
        locale: str | None = None,
    ) -> AnalyzeResponse:
        locale = locale or self.settings.default_locale
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        stage_timings: dict[str, int] = {}

        t0 = time.perf_counter()
        processed = preprocess_images(files, self.settings)
        images = [p.pil_image for p in processed]
        budget = self.settings.max_gemini_payload_bytes
        images = fit_images_to_budget(images, max_total_bytes=budget)
        stage_timings["preprocess_ms"] = int((time.perf_counter() - t0) * 1000)

        gemini_images = images
        media_resolution = self.settings.media_resolution_multi
        image_labels = [p.label for p in processed]

        t1 = time.perf_counter()
        llm, usage = await self.gemini.analyze_images_with_context(
            gemini_images,
            demo_context,
            media_resolution=media_resolution,
            locale=locale,
            image_labels=image_labels,
            total_images=len(processed),
        )
        stage_timings["gemini_ms"] = int((time.perf_counter() - t1) * 1000)

        t2 = time.perf_counter()
        llm = merge_sticker_sources(llm, images_analyzed=len(processed))

        identity_result = validate_identity(
            llm,
            min_confidence=self.settings.valuation_confidence_threshold,
        )
        if not identity_result.passed or identity_result.withheld_identity:
            IDENTITY_LOW_CONFIDENCE.inc()

        asset: AssetDetails = to_asset_details(llm, self.settings)
        asset = apply_demo_asset_identity(asset, demo_context)
        condition = AssetAnalysisService._build_condition(llm, len(processed))
        build_repair_plan(llm, condition)
        identifiers = build_identifiers(
            llm, asset.asset_tag_number, images_analyzed=len(processed)
        )
        demo_verification = build_demo_verification(demo_context, llm, identifiers)
        confidence = AssetAnalysisService._build_confidence(llm)

        market = resolve_market("IN", self.settings)
        fx = await get_fx_rate(self.settings, market.fx_target)  # type: ignore[arg-type]
        valuation = compute_valuation(
            llm,
            condition,
            identity_result,
            usd_to_display=fx.rate,
            market=market,
            valuation_confidence_min=self.settings.valuation_confidence_threshold,
            asset=asset,
            settings=self.settings,
        )
        _segment = resolve_segment_for_asset(llm, self.settings, market.region)
        valuation, climate_discount_pct = apply_climate_adjustment(valuation, demo_context, _segment)
        valuation = apply_demo_book_nbv(
            valuation,
            demo_context.book_nbv_inr,
            usd_to_inr=fx.rate,
            acquisition_date=demo_context.acquisition_date,
        )
        valuation = apply_nbv_comparison(valuation, market)

        demo_verification = demo_verification.model_copy(
            update={
                "location": demo_context.location,
                "location_profile": infer_location_profile(demo_context.location),
                "climate_valuation_points": build_climate_valuation_points(
                    demo_context, valuation, llm,
                    climate_discount_applied_pct=climate_discount_pct,
                    segment=_segment,
                ),
            }
        )
        demo_verification = enrich_demo_verification(
            demo_context,
            llm,
            identifiers,
            condition,
            asset,
            valuation,
            demo_verification,
        )

        if valuation.status in (ValuationStatus.WITHHELD, ValuationStatus.INDICATIVE_ONLY):
            VALUATION_WITHHELD.labels(status=valuation.status.value).inc()

        reasoning_summary = build_reasoning_summary(llm)
        cost = compute_cost(usage, fx, self.settings)

        review_required = (
            identity_result.withheld_identity
            or identity_result.generation_ambiguous
            or confidence.overall < self.settings.review_confidence_threshold
            or valuation.status == ValuationStatus.WITHHELD
            or (
                valuation.status == ValuationStatus.INDICATIVE_ONLY
                and valuation.confidence < self.settings.valuation_confidence_threshold
            )
            or identifiers_need_review(llm, asset.asset_tag_number, len(processed))
            or stickers_need_review(llm)
            or stickers_image_index_need_review(llm.stickers, len(processed))
            or damage_needs_review(llm)
            or (
                demo_context.asset_tag_number
                and not demo_verification.tag_number_match
            )
            or demo_verification.suggests_review
        )
        stage_timings["engines_ms"] = int((time.perf_counter() - t2) * 1000)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        PROCESSING_TIME_MS.observe(elapsed_ms)

        response = AnalyzeResponse(
            collage_base64=None,
            request_id=request_id,
            status="success",
            processing_time_ms=elapsed_ms,
            analysis_method=UnifiedViewMethod.MULTI_IMAGE,
            images_analyzed=len(processed),
            review_required=review_required,
            prompt_version=V6_PROMPT_VERSION,
            analysis_policy=AnalysisPolicy(
                valuation_confidence_threshold=self.settings.valuation_confidence_threshold,
                review_confidence_threshold=self.settings.review_confidence_threshold,
                reference_prices_source=reference_data_label(self.settings),
                fx_enabled=self.settings.fx_enabled,
                fx_source=fx.source,
                fx_is_fallback=fx.is_fallback,
                display_currency=self.settings.display_currency,
                market_region=self.settings.market_region,
            ),
            reasoning_summary=reasoning_summary,
            stage_timings_ms=stage_timings,
            asset=asset,
            condition=condition,
            identifiers=identifiers,
            valuation=client_valuation(valuation),
            confidence=confidence,
            token_usage=usage,
            cost=cost,
            demo_verification=demo_verification,
        )

        logger.info(
            "v6_demo_analysis_complete",
            request_id=request_id,
            catalog_id=demo_context.catalog_id,
            images_analyzed=len(processed),
            asset_name=asset.name,
            review_required=review_required,
            elapsed_ms=elapsed_ms,
        )
        return response
