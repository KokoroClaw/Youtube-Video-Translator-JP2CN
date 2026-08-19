"""OpenAI translation backend with strict, ID-preserving JSON output."""

import json
import os
import re
from openai import OpenAI

from src.backends.base import TranslationBackend


class OpenAIBackend(TranslationBackend):
    """OpenAI API backend for translation."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key or key.startswith("your_"):
            raise RuntimeError("OPENAI_API_KEY is missing or still a placeholder")
        self.client = OpenAI(api_key=key, max_retries=5, timeout=120.0)
        self.model = self._config.get(
            "model",
            os.environ.get("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini"),
        )

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        batch = self.translate_batch([text], source_lang, target_lang)
        return batch[0]

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        if not texts:
            return []

        lang_map = {"ja": "Japanese", "zh": "Chinese", "en": "English"}
        src = lang_map.get(source_lang, source_lang)
        tgt = lang_map.get(target_lang, target_lang)

        messages = [
            {
                "role": "system",
                "content": f"You are a professional translator. Translate {src} to {tgt}. "
                           "Keep subtitle wording natural, concise, and faithful. "
                           "Preserve every input id exactly once. "
                           "Tokens matching __GLOSSARY_N__ are protected terminology "
                           "markers: copy each token exactly and do not translate, alter, "
                           "split, or remove it."
            },
            {
                "role": "user",
                "content": json.dumps(
                    [{"id": i, "text": text} for i, text in enumerate(texts)],
                    ensure_ascii=False,
                )
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "subtitle_translations",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "translations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "translation": {"type": "string"},
                                    },
                                    "required": ["id", "translation"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["translations"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty translation response")

        payload = json.loads(content)
        translations = payload.get("translations", [])
        by_id = {item["id"]: item["translation"].strip() for item in translations}
        expected_ids = set(range(len(texts)))
        if set(by_id) != expected_ids or len(translations) != len(texts):
            raise RuntimeError(
                "OpenAI translation response did not contain every input id exactly once"
            )
        return [by_id[index] for index in range(len(texts))]

    def split_bilingual_segment(
        self, japanese: str, chinese: str, chunk_count: int
    ) -> list[dict[str, str]]:
        """Split existing bilingual wording without translating or rewriting it."""
        if chunk_count < 2:
            return [{"jp": japanese, "zh": chinese}]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You split one existing Japanese/Chinese subtitle into aligned "
                        "semantic chunks. Return exactly the requested number of chunks. "
                        "Only choose cut positions: never translate, rewrite, add, delete, "
                        "or reorder any character. Every Japanese and Chinese chunk must be "
                        "non-empty. Keep corresponding meanings together. Do not introduce "
                        "punctuation. Concatenating each language's chunks while ignoring "
                        "whitespace must reproduce its input exactly."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "chunk_count": chunk_count,
                        "japanese": japanese,
                        "chinese": chinese,
                    }, ensure_ascii=False),
                },
            ],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "aligned_subtitle_chunks",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "chunks": {
                                "type": "array",
                                "minItems": chunk_count,
                                "maxItems": chunk_count,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "jp": {"type": "string"},
                                        "zh": {"type": "string"},
                                    },
                                    "required": ["jp", "zh"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["chunks"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty subtitle split response")
        chunks = json.loads(content).get("chunks", [])
        if len(chunks) != chunk_count or any(
            not item.get("jp", "").strip() or not item.get("zh", "").strip()
            for item in chunks
        ):
            raise RuntimeError("OpenAI returned an invalid number of subtitle chunks")

        compact = lambda value: re.sub(r"\s+", "", value)
        if compact("".join(item["jp"] for item in chunks)) != compact(japanese):
            raise RuntimeError("OpenAI changed Japanese wording while splitting subtitles")
        if compact("".join(item["zh"] for item in chunks)) != compact(chinese):
            raise RuntimeError("OpenAI changed Chinese wording while splitting subtitles")
        return [
            {"jp": item["jp"].strip(), "zh": item["zh"].strip()}
            for item in chunks
        ]

    @property
    def name(self) -> str:
        return "OpenAI"
