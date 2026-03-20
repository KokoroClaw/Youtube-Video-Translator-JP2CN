"""
Anthropic (Claude) translation backend.
"""

import os
import anthropic

from src.backends.base import TranslationBackend


class AnthropicBackend(TranslationBackend):
    """Anthropic Claude API backend for translation."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = self._config.get("model", "claude-sonnet-4-20250514")

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

        user_content = (
            f"Translate the following {src} text{s} to {tgt}. "
            f"Translate each line separately and keep them in order.\n\n"
            + "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": user_content
                }
            ],
        )
        content = response.content[0].text.strip()
        lines = [l.split(".", 1)[-1].strip() for l in content.split("\n") if l.strip()]
        return lines[:len(texts)]

    @property
    def name(self) -> str:
        return "Anthropic"
