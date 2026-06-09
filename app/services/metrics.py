"""Prometheus metrics."""

from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "asset_analyze_requests_total",
    "Total asset analyze requests",
    ["status"],
)

REQUEST_LATENCY = Histogram(
    "asset_analyze_latency_seconds",
    "Asset analyze request latency",
    buckets=(0.5, 1, 2, 5, 10, 15, 30, 60),
)

ANALYSIS_METHOD = Counter(
    "asset_analysis_method_total",
    "Analysis method used",
    ["method"],
)

IDENTITY_LOW_CONFIDENCE = Counter(
    "asset_identity_low_confidence_total",
    "Analyses where identity validation failed or was withheld",
)

VALUATION_WITHHELD = Counter(
    "asset_valuation_withheld_total",
    "Analyses where valuation was withheld or indicative only",
    ["status"],
)

PROCESSING_TIME_MS = Histogram(
    "asset_processing_time_ms",
    "End-to-end server processing time in milliseconds",
    buckets=(500, 1000, 2000, 5000, 7500, 10000, 15000, 30000),
)
