"""Gemini thinking configuration."""

from app.config import Settings
from app.services.gemini import GeminiService


def test_flash_lite_does_not_support_thinking():
    svc = GeminiService(Settings(gemini_model="gemini-3.1-flash-lite"))
    assert svc._model_supports_thinking() is False


def test_flash_25_supports_thinking():
    svc = GeminiService(Settings(gemini_model="gemini-2.5-flash"))
    assert svc._model_supports_thinking() is True


def test_thinking_disabled_by_default_for_flash_lite():
    settings = Settings()
    assert settings.gemini_thinking_enabled is False
    assert settings.gemini_model == "gemini-3.1-flash-lite"
