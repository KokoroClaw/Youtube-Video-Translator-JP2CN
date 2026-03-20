"""
DeepSeek translation backend.
"""

import os
from openai import OpenAI

from src.backends.base import TranslationBackend


class DeepSeekBackend(TranslationBackend):
    """DeepSeek API backend for translation."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.client = OpenAI(
            api_key=key,
            base_url="https://api.deepseek.com",
        )
        self.model = self._config.get("model", "deepseek-chat")

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        batch = self.translate_batch([text], source_lang, target_lang)
        return batch[0]

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        lang_map = {"ja": "日语", "zh": "中文", "en": "英语"}
        src = lang_map.get(source_lang, source_lang)
        tgt = lang_map.get(target_lang, target_lang)

        messages = [
            {
                "role": "system",
                "content": f"你是一个专业的翻译助手。请将{src}翻译成{tgt}，保持原意通顺易懂。"
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
        # Parse numbered lines back
        lines = [l.split(".", 1)[-1].strip() for l in content.split("\n") if l.strip()]
        return lines[:len(texts)]

    @property
    def name(self) -> str:
        return "DeepSeek"
