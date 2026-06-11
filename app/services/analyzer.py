"""End-to-end asset analysis: preprocess -> Gemini -> engines -> response."""

import base64
import time
import uuid
from typing import BinaryIO

import structlog

from app.config import Settings
from app.models.responses import (
    AnalysisPolicy,
    AnalyzeResponse,
    AssetDetails,
    ConditionReport,
    ConfidenceScores,
    DamageSeverityCounts,
    LLMAnalysisResult,
    UnifiedViewMethod,
    ValuationStatus,
)
from app.services.reference_data import reference_data_label
from app.pipeline.collage_composer import build_collage
from app.pipeline.image_utils import fit_images_to_budget, image_to_bytes
from app.pipeline.preprocess import preprocess_images
from app.services.cost import compute_cost
from app.services.field_merger import _clean_list, to_asset_details
from app.markets.registry import resolve_market
from app.services.fx import get_fx_rate, get_usd_to_inr
from app.services.gemini import GeminiService
from app.services.condition_mapper import (
    resolve_condition_grade,
    build_damage_items,
    damage_needs_review,
    stickers_need_review,
)
from app.services.identity_validator import validate_identity
from app.services.metrics import (
    IDENTITY_LOW_CONFIDENCE,
    PROCESSING_TIME_MS,
    VALUATION_WITHHELD,
)
from app.services.nbv_engine import apply_nbv_comparison, apply_nbv_proxy
from app.services.placement_mapper import (
    build_identifiers,
    identifiers_need_review,
    merge_sticker_sources,
    stickers_image_index_need_review,
)
from app.services.reasoning_summary import build_reasoning_summary
from app.services.repair_policy import build_repair_plan
from app.services.valuation_display import client_valuation
from app.services.history_repository import get_history_repository
from app.services.valuation_engine import compute_valuation

logger = structlog.get_logger()

UploadTuple = tuple[BinaryIO, str, bytes]


class AssetAnalysisService:
    def __init__(self, settings: Settings, gemini: GeminiService):
        self.settings = settings
        self.gemini = gemini

    async def analyze(
        self,
        files: list[UploadTuple],
        method: UnifiedViewMethod,
        locale: str | None = None,
        market_region: str | None = None,
        processing_mode: str | None = None,
        api_route: str | None = None,
    ) -> AnalyzeResponse:
        market = resolve_market(market_region, self.settings)
        locale = locale or market.default_locale
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        stage_timings: dict[str, int] = {}

        t0 = time.perf_counter()
        processed = preprocess_images(files, self.settings)
        images = [p.pil_image for p in processed]
        budget = self.settings.max_gemini_payload_bytes
        images = fit_images_to_budget(images, max_total_bytes=budget)
        stage_timings["preprocess_ms"] = int((time.perf_counter() - t0) * 1000)

        collage_base64: str | None = None
        if method == UnifiedViewMethod.COLLAGE:
            collage = build_collage(images)
            [collage] = fit_images_to_budget([collage], max_total_bytes=budget)
            gemini_images = [collage]
            media_resolution = self.settings.media_resolution_collage
            collage_b64 = base64.b64encode(image_to_bytes(collage)).decode("ascii")
            collage_base64 = f"data:image/jpeg;base64,{collage_b64}"
        else:
            gemini_images = images
            media_resolution = self.settings.media_resolution_multi

        image_labels = [p.label for p in processed]
        t1 = time.perf_counter()
        llm, usage = await self.gemini.analyze_images(
            gemini_images,
            media_resolution=media_resolution,
            locale=locale,
            image_labels=image_labels if method == UnifiedViewMethod.MULTI_IMAGE else None,
            total_images=len(processed),
            market_region=market.region,
        )
        stage_timings["gemini_ms"] = int((time.perf_counter() - t1) * 1000)

        t2 = time.perf_counter()
        llm = merge_sticker_sources(llm, images_analyzed=len(processed))

        identity_result = validate_identity(
            llm,
            min_confidence=self.settings.field_confidence_threshold,
        )
        if not identity_result.passed or identity_result.withheld_identity:
            IDENTITY_LOW_CONFIDENCE.inc()

        asset: AssetDetails = to_asset_details(llm, self.settings)
        condition = self._build_condition(llm, len(processed))
        build_repair_plan(llm, condition)
        identifiers = build_identifiers(
            llm, asset.asset_tag_number, images_analyzed=len(processed)
        )
        confidence = self._build_confidence(llm)

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
        valuation = apply_nbv_proxy(
            valuation,
            llm,
            usd_to_display=fx.rate,
            market=market,
            asset=asset,
            settings=self.settings,
        )
        valuation = apply_nbv_comparison(valuation, market)

        if valuation.status in (ValuationStatus.WITHHELD, ValuationStatus.INDICATIVE_ONLY):
            VALUATION_WITHHELD.labels(status=valuation.status.value).inc()

        reasoning_summary = build_reasoning_summary(llm)
        cost_fx = await get_usd_to_inr(self.settings)
        cost = compute_cost(usage, cost_fx, self.settings)

        review_required = (
            identity_result.withheld_identity
            or confidence.overall < self.settings.review_confidence_threshold
            or identifiers_need_review(llm, asset.asset_tag_number, len(processed))
            or stickers_need_review(llm)
            or stickers_image_index_need_review(llm.stickers, len(processed))
            or damage_needs_review(llm)
        )
        stage_timings["engines_ms"] = int((time.perf_counter() - t2) * 1000)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        PROCESSING_TIME_MS.observe(elapsed_ms)

        target_ms = self.settings.analysis_target_ms
        if target_ms > 0 and elapsed_ms > target_ms:
            logger.warning(
                "analysis_exceeded_target",
                request_id=request_id,
                elapsed_ms=elapsed_ms,
                target_ms=target_ms,
                stage_timings=stage_timings,
            )

        response = AnalyzeResponse(
            collage_base64=collage_base64,
            request_id=request_id,
            status="success",
            processing_time_ms=elapsed_ms,
            analysis_method=method,
            images_analyzed=len(processed),
            review_required=review_required,
            prompt_version=self.settings.prompt_version,
            analysis_policy=AnalysisPolicy(
                valuation_confidence_threshold=self.settings.valuation_confidence_threshold,
                review_confidence_threshold=self.settings.review_confidence_threshold,
                reference_prices_source=reference_data_label(self.settings, market.region),
                fx_enabled=self.settings.fx_enabled,
                fx_source=fx.source,
                fx_is_fallback=fx.is_fallback,
                display_currency=market.currency,
                market_region=market.region,
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
        )

        entry_id, saved_to_db, image_urls = await get_history_repository(
            self.settings
        ).save_analysis(
            user_id=self.settings.demo_user_id,
            request_id=request_id,
            response=response,
            processed_images=processed,
            method=method,
            processing_mode=processing_mode,
            api_route=api_route,
        )
        response.entry_id = entry_id
        response.saved_to_db = saved_to_db
        response.image_urls = image_urls

        logger.info(
            "analysis_complete",
            request_id=request_id,
            method=method.value,
            images_analyzed=len(processed),
            asset_name=asset.name,
            damage_count=condition.damage_count,
            review_required=review_required,
            valuation_status=valuation.status.value,
            identity_passed=identity_result.passed,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_cost_usd=cost.total_cost_usd,
            elapsed_ms=elapsed_ms,
            stage_timings=stage_timings,
            saved_to_db=saved_to_db,
        )
        return response

    @staticmethod
    def _build_condition(llm: LLMAnalysisResult, images_analyzed: int) -> ConditionReport:
        items = build_damage_items(llm, images_analyzed)
        counts = DamageSeverityCounts()
        for item in items:
            sev = (item.severity or "").strip().lower()
            if sev == "minor":
                counts.minor += 1
            elif sev == "moderate":
                counts.moderate += 1
            elif sev == "severe":
                counts.severe += 1

        score = llm.condition_score
        if score is not None:
            if isinstance(score, float):
                score = int(round(score))
            if isinstance(score, int):
                if 1 <= score <= 10:
                    score = score * 10
                score = max(0, min(100, score))
            else:
                score = None

        return ConditionReport(
            grade=resolve_condition_grade(llm.condition_grade, score or llm.condition_score),
            overall_score=score,
            summary=llm.condition_summary,
            cosmetic_condition=llm.cosmetic_condition,
            structural_condition=llm.structural_condition,
            functional_status=llm.functional_status,
            cleanliness=llm.cleanliness,
            wear_level=llm.wear_level,
            usability=llm.usability,
            repair_recommendation=llm.repair_recommendation,
            estimated_remaining_life=llm.estimated_remaining_life,
            missing_parts=_clean_list(llm.missing_parts),
            functional_issues=_clean_list(llm.functional_issues),
            positive_aspects=_clean_list(llm.positive_aspects),
            has_damage=bool(items),
            damage_count=len(items),
            damage_by_severity=counts,
            damage_items=items,
        )

    @staticmethod
    def _build_confidence(llm: LLMAnalysisResult) -> ConfidenceScores:
        parts = [
            llm.confidence_asset_name,
            llm.confidence_asset_condition,
            llm.confidence_asset_description,
            llm.confidence_asset_tag_number,
        ]
        overall = round(sum(parts) / len(parts), 3) if parts else 0.0
        return ConfidenceScores(
            overall=overall,
            asset_name=round(llm.confidence_asset_name, 3),
            asset_condition=round(llm.confidence_asset_condition, 3),
            asset_description=round(llm.confidence_asset_description, 3),
            asset_tag_number=round(llm.confidence_asset_tag_number, 3),
            valuation=round(llm.valuation_confidence, 3),
        )
