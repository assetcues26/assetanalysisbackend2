"""Format valuation / climate notes as punctuated bullet points."""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"(])')
_ABBREV_PROTECT = re.compile(r'\b(e\.g|i\.e|vs|approx|Mr|Mrs|Dr)\.\s', re.IGNORECASE)


def normalize_bullet(text: str) -> str:
    """Ensure a single insight ends with terminal punctuation."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def split_prose_to_bullets(text: str) -> list[str]:
    """Split LLM paragraphs into sentence-level bullets."""
    raw = (text or "").strip()
    if not raw:
        return []

    protected = _ABBREV_PROTECT.sub(lambda m: m.group(0).replace(". ", "§ "), raw)
    chunks: list[str] = []
    for part in re.split(r"[;\n]+", protected):
        part = part.strip()
        if not part:
            continue
        sentences = _SENTENCE_SPLIT.split(part)
        chunks.extend(sentences)

    bullets = [normalize_bullet(c.replace("§ ", ". ")) for c in chunks if c.strip()]
    return [b for b in bullets if b]


def _bullet_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def dedupe_bullets(bullets: list[str]) -> list[str]:
    """Drop near-duplicate insights (substring / prefix match)."""
    result: list[str] = []
    keys: list[str] = []
    for bullet in bullets:
        norm = normalize_bullet(bullet)
        if not norm:
            continue
        key = _bullet_key(norm)
        if not key:
            continue
        if any(key in existing or existing in key for existing in keys):
            continue
        keys.append(key)
        result.append(norm)
    return result
