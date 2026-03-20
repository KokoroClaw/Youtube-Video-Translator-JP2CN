"""
Translator factory - auto-selects first available backend.
"""

import os
from typing import Protocol

from src.backends.base import TranslationBackend
from src.backends.deepseek import DeepSeekBackend
from src.backends.openai import OpenAIBackend
from src.backends.anthropic import AnthropicBackend
from src.backends.gemini import GeminiBackend
from src.backends.groq import GroqBackend
from src.backends.ollama import OllamaBackend
from src.backends.minimax import MiniMaxBackend
from src.backends.zhipu import ZhipuBackend
from src.backends.google import GoogleBackend


# Batch size for translation requests
BATCH_SIZE = 20


class Translator:
    """
    Factory class that auto-selects the first available translation backend.

    Priority order: DeepSeek → OpenAI → MiniMax → Google → Groq → Ollama → Anthropic → Zhipu → Google (fallback)
    Falls back to Google Translate if no API keys are configured.
    """

    # Ordered list of (backend_class, env_var_or_check) tuples
    BACKENDS = [
        (DeepSeekBackend, "DEEPSEEK_API_KEY"),
        (OpenAIBackend, "OPENAI_API_KEY"),
        (MiniMaxBackend, "MINIMAX_API_KEY"),
        (GeminiBackend, "GOOGLE_API_KEY"),
        (GroqBackend, "GROQ_API_KEY"),
        (OllamaBackend, "OLLAMA"),      # special: check base URL
        (AnthropicBackend, "ANTHROPIC_API_KEY"),
        (ZhipuBackend, "ZHIPU_API_KEY"),
        (GoogleBackend, None),          # always available
    ]

    def __init__(self):
        self._backend: TranslationBackend = None
        self._select_backend()

    def _select_backend(self) -> None:
        """Select the first available backend."""
        for backend_cls, env_check in self.BACKENDS:
            if env_check is None:
                # Last resort backend (Google) - always available
                self._backend = backend_cls()
                print(f"  [Translator] Using {self._backend.name} (fallback)")
                return

            # Check if env var is set and non-empty
            key = os.environ.get(env_check, "").strip()
            if key:
                try:
                    self._backend = backend_cls(api_key=key)
                    print(f"  [Translator] Using {self._backend.name}")
                    return
                except Exception as e:
                    print(f"  [Translator] {backend_cls.__name__} failed: {e}, trying next...")

        # Fallback to Google if nothing else works
        self._backend = GoogleBackend()
        print(f"  [Translator] Using {self._backend.name} (final fallback)")

    @property
    def backend_name(self) -> str:
        """Return the name of the active backend."""
        return self._backend.name if self._backend else "None"

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        """Translate a single text segment."""
        return self._backend.translate(text, source_lang, target_lang)

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        """Translate multiple text segments in batches."""
        all_results = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            results = self._backend.translate_batch(batch, source_lang, target_lang)
            all_results.extend(results)
            print(f"    Translated batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1}")
        return all_results

    def translate_segments(self, segments: list[dict]) -> list[dict]:
        """
        Translate a list of Whisper segments (with 'text' field).

        Args:
            segments: List of dicts with keys: start, end, text, language.

        Returns:
            List of dicts with added 'translation' field.
        """
        texts = [seg["text"] for seg in segments]
        translations = self.translate_batch(texts)

        result = []
        for seg, trans in zip(segments, translations):
            result.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "translation": trans,
                "language": seg.get("language", "ja"),
            })
        return result
