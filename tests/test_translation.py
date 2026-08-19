import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.backends.openai import OpenAIBackend
from src.translator import Translator, _normalize_chinese_punctuation


def _response(payload):
    return SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
    ])


class OpenAITranslationTests(unittest.TestCase):
    def test_chinese_punctuation_style(self):
        result = _normalize_chinese_punctuation(
            "你好，世界。下一句,没有英文句号.问号保留？"
        )

        self.assertEqual(result, "你好 世界下一句 没有英文句号问号保留？")

    @patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "sk-test-not-a-real-key"},
        clear=False,
    )
    def test_translator_restores_glossary_terms_before_punctuation_cleanup(self):
        translator = Translator(glossary_terms=[
            {"source": "先輩", "target": "前辈", "enabled": True},
        ])
        translator._backend.translate_batch = Mock(
            side_effect=lambda texts, *_args: [f"你好，{texts[0]}。"]
        )

        result = translator.translate_batch(["先輩"])

        self.assertEqual(result, ["你好 前辈"])

    def test_translation_is_reordered_by_stable_id(self):
        backend = OpenAIBackend(api_key="sk-test-not-a-real-key")
        create = Mock(return_value=_response({
            "translations": [
                {"id": 1, "translation": "第二句"},
                {"id": 0, "translation": "第一句"},
            ]
        }))
        backend.client.chat.completions.create = create

        result = backend.translate_batch(["一番", "二番"])

        self.assertEqual(result, ["第一句", "第二句"])
        self.assertEqual(
            create.call_args.kwargs["response_format"]["type"],
            "json_schema",
        )

    def test_translation_rejects_missing_ids(self):
        backend = OpenAIBackend(api_key="sk-test-not-a-real-key")
        backend.client.chat.completions.create = Mock(return_value=_response({
            "translations": [{"id": 0, "translation": "只有一句"}]
        }))

        with self.assertRaisesRegex(RuntimeError, "every input id"):
            backend.translate_batch(["一番", "二番"])

    def test_openai_semantic_split_preserves_existing_bilingual_wording(self):
        backend = OpenAIBackend(api_key="sk-test-not-a-real-key")
        backend.client.chat.completions.create = Mock(return_value=_response({
            "chunks": [
                {"jp": "今日は", "zh": "今天"},
                {"jp": "晴れです", "zh": "天气晴朗"},
            ]
        }))

        result = backend.split_bilingual_segment(
            "今日は晴れです", "今天天气晴朗", 2
        )

        self.assertEqual(len(result), 2)
        self.assertEqual("".join(item["jp"] for item in result), "今日は晴れです")
        self.assertEqual("".join(item["zh"] for item in result), "今天天气晴朗")

    @patch.dict(
        os.environ,
        {
            "TRANSLATION_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
            "DEEPSEEK_API_KEY": "configured-but-not-selected",
        },
        clear=False,
    )
    def test_explicit_openai_selection_ignores_deepseek_priority(self):
        translator = Translator()
        self.assertEqual(translator.backend_name, "OpenAI")


if __name__ == "__main__":
    unittest.main()
