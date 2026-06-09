"""Load Gemini prompt templates from app/prompts/."""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent
ANALYSIS_PROMPT = "analysis.txt"
ANALYSIS_V6_DEMO_PROMPT = "analysis_v6_demo.txt"


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_analysis_prompt() -> str:
    """Return the asset analysis prompt (one or many images, exhaustive damage)."""
    return load_prompt(ANALYSIS_PROMPT)


def get_analysis_v6_demo_prompt() -> str:
    """Return the V6 demo prompt (ERP context + images, isolated from v1)."""
    return load_prompt(ANALYSIS_V6_DEMO_PROMPT)
