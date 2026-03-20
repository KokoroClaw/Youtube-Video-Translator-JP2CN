"""
Ollama local translation backend.
"""

import os
from openai import OpenAI

from src.backends.base import TranslationBackend


class OllamaBackend(TranslationBackend):
    """Ollama local LLM backend for translation (OpenAI-compatible)."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = OpenAI(
            api_key="ollama",  # Ollama doesn't need a real key
            base_url=base_url,
        )
        self.model = os.environ.get("OLLAMA_MODEL", "llama3")

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

        messages = [
            {
                "role": "system",
                "content": f"You are a professional translator. Translate {src} to {tgt}. "
                           f"Keep the meaning natural and fluent. Output only translations, "
                           f"one per line, numbered."
            },
            {
                "role": "user",
                "content": "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        lines = [l.split(".", 1)[-1].strip() for l in content.split("\n") if l.strip()]
        return lines[:len(texts)]

    @property
    def name(self) -> str:
        return f"Ollama ({self.model})"
