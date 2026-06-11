"""Pydantic response and domain models (clean, grouped JSON for UI)."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models.history import ImageUrls


class UnifiedViewMethod(str, Enum):
    COLLAGE = "collage"
    MULTI_IMAGE = "multi_image"


class RepairNeeded(str, Enum):
    NONE = "none"
    COSMETIC_ONLY = "cosmetic_only"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


class RepairUrgency(str, Enum):
    NONE = "none"
    MONITOR = "monitor"
    SCHEDULED = "scheduled"
    IMMEDIATE = "immediate"


class MarketSegment(str, Enum):
    CONSUMER_ELECTRONICS = "consumer_electronics"
    IT_EQUIPMENT = "it_equipment"
    INDUSTRIAL = "industrial"
    FURNITURE = "furniture"
    VEHICLE = "vehicle"
    HVAC = "hvac"
    OTHER = "other"


class ValuationStatus(str, Enum):
    OK = "ok"
    WITHHELD = "withheld"
    INDICATIVE_ONLY = "indicative_only"


# --------------------------------------------------------------------------- #
# Asset details
# --------------------------------------------------------------------------- #
class AssetDetails(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    estimated_dimensions: Optional[str] = None
    estimated_model_years: Optional[str] = None
    estimated_age_years: Optional[str] = None
    age_as_of_year: Optional[int] = None
    estimated_age: Optional[str] = None  # legacy combined string; prefer fields above
    quantity: int = 1
    serial_number: Optional[str] = None
    asset_tag_number: Optional[str] = None
    specifications: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    distinguishing_features: list[str] = Field(default_factory=list)
    description: Optional[str] = None


# --------------------------------------------------------------------------- #
# Placement (shared by damage, barcode, stickers)
# --------------------------------------------------------------------------- #
class PlacementInfo(BaseModel):
    asset_location: Optional[str] = None
    horizontal: Optional[str] = None
    vertical: Optional[str] = None
    seen_in_image: Optional[int] = None
    in_frame_position: Optional[str] = None
    description: Optional[str] = None


# --------------------------------------------------------------------------- #
# Condition / damage
# --------------------------------------------------------------------------- #
class DamageItem(BaseModel):
    location: Optional[str] = None
    type: Optional[str] = None
    severity: Optional[str] = None
    seen_in_image: Optional[int] = None
    detail: Optional[str] = None
    affects_function: Optional[bool] = None
    repair_action: Optional[str] = None
    repair_needed: Optional[RepairNeeded] = None
    repair_urgency: Optional[RepairUrgency] = None
    acceptable_wear: Optional[bool] = None
    placement: Optional[PlacementInfo] = None


class RepairPlanItem(BaseModel):
    damage_type: Optional[str] = None
    location: Optional[str] = None
    repair_needed: RepairNeeded = RepairNeeded.NONE
    repair_urgency: RepairUrgency = RepairUrgency.NONE
    acceptable_wear: bool = False
    rationale: Optional[str] = None


class RepairPlan(BaseModel):
    overall_repair_needed: bool = False
    summary: Optional[str] = None
    items: list[RepairPlanItem] = Field(default_factory=list)


class DamageSeverityCounts(BaseModel):
    minor: int = 0
    moderate: int = 0
    severe: int = 0


class ConditionReport(BaseModel):
    grade: Optional[str] = None
    overall_score: Optional[int] = Field(default=None, ge=0, le=100)
    summary: Optional[str] = None
    cosmetic_condition: Optional[str] = None
    structural_condition: Optional[str] = None
    functional_status: Optional[str] = None
    cleanliness: Optional[str] = None
    wear_level: Optional[str] = None
    usability: Optional[str] = None
    repair_recommendation: Optional[str] = None
    estimated_remaining_life: Optional[str] = None
    missing_parts: list[str] = Field(default_factory=list)
    functional_issues: list[str] = Field(default_factory=list)
    positive_aspects: list[str] = Field(default_factory=list)
    has_damage: bool = False
    damage_count: int = 0
    damage_by_severity: DamageSeverityCounts = Field(default_factory=DamageSeverityCounts)
    damage_items: list[DamageItem] = Field(default_factory=list)
    repair_plan: Optional[RepairPlan] = None


# --------------------------------------------------------------------------- #
# Identifiers (tags / labels / barcode)
# --------------------------------------------------------------------------- #
class BarcodeDetails(BaseModel):
    present: bool = False
    readable: bool = False
    placement: Optional[PlacementInfo] = None
    detection_reasoning: Optional[str] = None


class StickerItem(BaseModel):
    label_text: str
    sticker_type: Optional[str] = None
    placement: Optional[PlacementInfo] = None


class Identifiers(BaseModel):
    asset_tag_number: Optional[str] = None
    asset_tag_number_raw: Optional[str] = None
    tag_readable: bool = False
    tag_position: Optional[str] = None
    tag_detection_reasoning: Optional[str] = None
    visible_labels: list[str] = Field(default_factory=list)
    barcode: BarcodeDetails = Field(default_factory=BarcodeDetails)
    stickers: list[StickerItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #
class MoneyRange(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class ValuationAmount(BaseModel):
    usd: MoneyRange = Field(default_factory=MoneyRange)
    inr: MoneyRange = Field(default_factory=MoneyRange)
    display: MoneyRange = Field(default_factory=MoneyRange)
    display_currency: str = "INR"


class NbvEstimate(BaseModel):
    usd: MoneyRange = Field(default_factory=MoneyRange)
    inr: MoneyRange = Field(default_factory=MoneyRange)
    display: MoneyRange = Field(default_factory=MoneyRange)
    display_currency: str = "INR"
    method: str = "age_derived_proxy"
    age_years_used: Optional[float] = None
    depreciation_rate_used: Optional[float] = None
    disclaimer: str = (
        "Age and depreciation rules only — excludes damage adjustments. "
        "Not certified accounting NBV; use ERP book data when available."
    )


class Valuation(BaseModel):
    status: ValuationStatus = ValuationStatus.OK
    as_is: ValuationAmount = Field(default_factory=ValuationAmount)
    like_new_reference: ValuationAmount = Field(default_factory=ValuationAmount)
    nbv: Optional[NbvEstimate] = None
    nbv_exceeds_as_is: Optional[bool] = None
    nbv_vs_as_is_note: Optional[str] = None
    currency_note: str = "All amounts in Indian Rupees (₹) for India market context."
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    assumptions: Optional[str] = None
    disclaimer: str = ""


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #
class ConfidenceScores(BaseModel):
    overall: float = 0.0
    asset_name: float = 0.0
    asset_condition: float = 0.0
    asset_description: float = 0.0
    asset_tag_number: float = 0.0
    valuation: float = 0.0


# --------------------------------------------------------------------------- #
# Cost / tokens
# --------------------------------------------------------------------------- #
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Breakdown of input_tokens (image_tokens + text_tokens == input_tokens)
    image_tokens: int = 0
    text_tokens: int = 0
    images_sent_to_gemini: int = 0
    per_image_token_budget: int = 0
    estimated_image_tokens: int = 0


class CostInfo(BaseModel):
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    usd_to_inr: float
    total_cost_inr: float
    fx_source: str
    fx_is_fallback: bool
    fx_as_of: Optional[str] = None


# --------------------------------------------------------------------------- #
# Top-level response
# --------------------------------------------------------------------------- #
class IdentityCandidate(BaseModel):
    label: str
    visual_cues_for: list[str] = Field(default_factory=list)
    visual_cues_against: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class ReasoningSummary(BaseModel):
    identity_candidates: list[IdentityCandidate] = Field(default_factory=list)
    selected_identity_rationale: Optional[str] = None
    uncertainty_flags: list[str] = Field(default_factory=list)
    damage_notes: Optional[str] = None
    repair_judgement_notes: Optional[str] = None
    narrative: Optional[str] = None


class TagZoomHint(BaseModel):
    """Display-only crop region for tag zoom (percentages of image dimensions)."""

    image_index: Optional[int] = None
    x_pct: float = Field(ge=0.0, le=100.0)
    y_pct: float = Field(ge=0.0, le=100.0)
    width_pct: float = Field(gt=0.0, le=100.0)
    height_pct: float = Field(gt=0.0, le=100.0)


class PhotoAngleStatus(BaseModel):
    id: str
    label: str
    required: bool = True
    satisfied: bool = False


class DemoVerification(BaseModel):
    """V6 demo ERP cross-checks (vision vs input payload)."""

    erp_tag_number: Optional[str] = None
    detected_tag_number: Optional[str] = None
    detected_tag_number_raw: Optional[str] = None
    tag_number_match: bool = False
    tag_match_note: Optional[str] = None
    erp_make: Optional[str] = None
    erp_model: Optional[str] = None
    erp_book_nbv_inr: Optional[float] = None
    vision_make: Optional[str] = None
    vision_model: Optional[str] = None
    make_match: Optional[bool] = None
    model_match: Optional[bool] = None
    location: Optional[str] = None
    location_profile: Optional[str] = None
    climate_valuation_note: Optional[str] = None
    climate_valuation_points: list[str] = Field(default_factory=list)
    tag_visible: Optional[bool] = None
    tag_readable: Optional[bool] = None
    erp_category: Optional[str] = None
    vision_category: Optional[str] = None
    category_match: Optional[bool] = None
    rust_corrosion_noted: Optional[bool] = None
    functional_appearance: Optional[str] = None
    photo_coverage_score: Optional[int] = Field(default=None, ge=1, le=5)
    photo_angles: list[PhotoAngleStatus] = Field(default_factory=list)
    nbv_vs_market_note: Optional[str] = None
    nbv_vs_market_points: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    tag_zoom_hint: Optional[TagZoomHint] = None
    suggests_review: bool = False


class AnalysisPolicy(BaseModel):
    """Non-secret thresholds and data sources applied for this deployment."""

    valuation_confidence_threshold: float
    review_confidence_threshold: float
    reference_prices_source: str
    fx_enabled: bool
    fx_source: str
    fx_is_fallback: bool
    display_currency: str = "INR"
    market_region: str = "IN"


class AnalyzeResponse(BaseModel):
    collage_base64: Optional[str] = None
    request_id: str
    entry_id: Optional[str] = None
    saved_to_db: bool = False
    image_urls: Optional[ImageUrls] = None
    status: str = "success"
    processing_time_ms: int
    analysis_method: UnifiedViewMethod
    images_analyzed: int
    review_required: bool = False
    prompt_version: str = "v2"
    analysis_policy: Optional[AnalysisPolicy] = None
    reasoning_summary: Optional[ReasoningSummary] = None
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)
    asset: AssetDetails
    condition: ConditionReport
    identifiers: Identifiers
    valuation: Valuation
    confidence: ConfidenceScores
    token_usage: TokenUsage
    cost: CostInfo
    demo_verification: Optional[DemoVerification] = None


class HealthResponse(BaseModel):
    status: str
    gemini_configured: bool


# --------------------------------------------------------------------------- #
# LLM structured-output schema (passed to Gemini as response_schema)
# Keep flat and simple types so the JSON schema stays clean.
# --------------------------------------------------------------------------- #
class LLMIdentityCandidate(BaseModel):
    label: Optional[str] = None
    visual_cues_for: list[str] = Field(default_factory=list)
    visual_cues_against: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class LLMReasoningTrace(BaseModel):
    identity_candidates: list[LLMIdentityCandidate] = Field(default_factory=list)
    selected_identity_rationale: Optional[str] = None
    uncertainty_flags: list[str] = Field(default_factory=list)
    damage_notes: Optional[str] = None
    repair_judgement_notes: Optional[str] = None
    age_estimation_rationale: Optional[str] = None
    valuation_deliberation_notes: Optional[str] = None


class LLMValuationInputs(BaseModel):
    reference_like_new_usd: Optional[float] = None
    condition_adjustment_pct: Optional[float] = None
    age_years_min: Optional[float] = None
    age_years_max: Optional[float] = None
    market_segment: Optional[str] = None
    valuation_rationale: Optional[str] = None


class LLMDamageItem(BaseModel):
    location: Optional[str] = None
    type: Optional[str] = None
    severity: Optional[str] = None
    seen_in_image: Optional[int] = None
    horizontal: Optional[str] = None
    vertical: Optional[str] = None
    in_frame_position: Optional[str] = None
    detail: Optional[str] = None
    affects_function: Optional[bool] = None
    repair_action: Optional[str] = None
    repair_needed: Optional[str] = None
    repair_urgency: Optional[str] = None
    acceptable_wear: Optional[bool] = None


class LLMStickerItem(BaseModel):
    label_text: Optional[str] = None
    sticker_type: Optional[str] = None
    asset_location: Optional[str] = None
    horizontal: Optional[str] = None
    vertical: Optional[str] = None
    seen_in_image: Optional[int] = None
    in_frame_position: Optional[str] = None


class LLMAnalysisResult(BaseModel):
    # Reasoning (fill before conclusions)
    reasoning: LLMReasoningTrace = Field(default_factory=LLMReasoningTrace)
    valuation_inputs: LLMValuationInputs = Field(default_factory=LLMValuationInputs)

    # Identity
    asset_name: Optional[str] = None
    category: Optional[str] = None
    asset_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    estimated_dimensions: Optional[str] = None
    estimated_model_year_min: Optional[int] = None
    estimated_model_year_max: Optional[int] = None
    estimated_age: Optional[str] = None  # legacy; do not set from prompt
    quantity: Optional[int] = None
    serial_number: Optional[str] = None
    specifications: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    distinguishing_features: list[str] = Field(default_factory=list)
    description: Optional[str] = None

    # Identifiers (before condition — less likely to be truncated)
    asset_tag_number: Optional[str] = None
    tag_readable: Optional[bool] = None
    tag_detection_reasoning: Optional[str] = None
    barcode_present: Optional[bool] = None
    barcode_asset_location: Optional[str] = None
    barcode_horizontal: Optional[str] = None
    barcode_vertical: Optional[str] = None
    barcode_seen_in_image: Optional[int] = None
    barcode_in_frame_position: Optional[str] = None
    barcode_position: Optional[str] = None
    stickers: list[LLMStickerItem] = Field(default_factory=list)
    visible_labels: list[str] = Field(default_factory=list)
    damage_items: list[LLMDamageItem] = Field(default_factory=list)

    # Condition (detailed)
    condition_summary: Optional[str] = None
    condition_grade: Optional[str] = None
    condition_score: Optional[int] = None
    cosmetic_condition: Optional[str] = None
    structural_condition: Optional[str] = None
    functional_status: Optional[str] = None
    cleanliness: Optional[str] = None
    wear_level: Optional[str] = None
    usability: Optional[str] = None
    repair_recommendation: Optional[str] = None
    estimated_remaining_life: Optional[str] = None
    missing_parts: list[str] = Field(default_factory=list)
    functional_issues: list[str] = Field(default_factory=list)
    positive_aspects: list[str] = Field(default_factory=list)

    # Confidence
    confidence_asset_name: float = 0.0
    confidence_asset_condition: float = 0.0
    confidence_asset_description: float = 0.0
    confidence_asset_tag_number: float = 0.0

    # Legacy valuation hints (ignored by engine; kept for schema compatibility)
    estimated_value_usd_min: Optional[float] = None
    estimated_value_usd_max: Optional[float] = None
    like_new_value_usd_min: Optional[float] = None
    like_new_value_usd_max: Optional[float] = None
    valuation_confidence: float = 0.0
    valuation_assumptions: Optional[str] = None
