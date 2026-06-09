"""Token-usage cost calculation in USD and INR."""

from app.config import Settings
from app.models.responses import CostInfo, TokenUsage
from app.services.fx import FxResult


def compute_cost(
    usage: TokenUsage,
    fx: FxResult,
    settings: Settings,
) -> CostInfo:
    input_cost_usd = usage.input_tokens / 1_000_000 * settings.gemini_input_usd_per_1m
    output_cost_usd = usage.output_tokens / 1_000_000 * settings.gemini_output_usd_per_1m
    total_cost_usd = input_cost_usd + output_cost_usd
    total_cost_inr = total_cost_usd * fx.rate

    return CostInfo(
        model=settings.gemini_model,
        input_usd_per_1m=settings.gemini_input_usd_per_1m,
        output_usd_per_1m=settings.gemini_output_usd_per_1m,
        input_cost_usd=round(input_cost_usd, 6),
        output_cost_usd=round(output_cost_usd, 6),
        total_cost_usd=round(total_cost_usd, 6),
        usd_to_inr=round(fx.rate, 4),
        total_cost_inr=round(total_cost_inr, 4),
        fx_source=fx.source,
        fx_is_fallback=fx.is_fallback,
        fx_as_of=fx.as_of,
    )
