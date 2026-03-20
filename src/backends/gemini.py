"""
Google Gemini translation backend.
"""

import os
import google.genai as genai

from src.backends.base import TranslationBackend


class GeminiBackend(TranslationBackend):
    """Google Gemini API backend for translation."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        genai.configure(api_key=key)
        self.model_name = self._config.get("model", "gemini-2.0-flash")

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        batch = self.translate_batch([text], source_lang, target_lang)
        return batch[0]

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        lang_map = {"ja": "Japanese", "zh": "Chinese", "en": "English"}
        src = lang_map.get(source_lang, source_lang)
        tgt = lang_map.get(target_lang, target_lang)

        prompt = (
            f"Translate the following {src} text{s} to {tgt}. "
            f"Translate each line separately and keep them in order.\n\n"
            + "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
        )

        model = genai.GenerativeModel(self.model_name)
        response = model.generate_content(prompt)
        content = response.text.strip()
        lines = [l.split(".", 1)[-1].strip() for l in content.split("\n") if l.strip()]
        return lines[:len(texts)]

    @property
    def name(self) -> str:
        return "Google Gemini"
