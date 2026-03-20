"""
Google (deep-translator) fallback translation backend.
"""

from deep_translator import GoogleTranslator

from src.backends.base import TranslationBackend


class GoogleBackend(TranslationBackend):
    """Google Translate backend via deep-translator (free, no API key)."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        lang_map = {"ja": "ja", "zh": "zh-CN", "en": "en"}
        src = lang_map.get(source_lang, source_lang)
        tgt = lang_map.get(target_lang, target_lang)

        result = GoogleTranslator(source=src, target=tgt).translate(text)
        return result or ""

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        lang_map = {"ja": "ja", "zh": "zh-CN", "en": "en"}
        src = lang_map.get(source_lang, source_lang)
        tgt = lang_map.get(target_lang, target_lang)

        results = GoogleTranslator(source=src, target=tgt).translate_batch(texts)
        return list(results)

    @property
    def name(self) -> str:
        return "Google Translate"
