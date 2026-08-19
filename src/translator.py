"""Translation backend selection and batched subtitle translation."""

import os

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
from src.glossary import GlossaryProtector, GlossaryStore


# Batch size for translation requests (loaded from env, default 100)
BATCH_SIZE = int(os.environ.get("TRANSLATION_BATCH_SIZE", "100"))


def _normalize_chinese_punctuation(text: str) -> str:
    """Apply the project's subtitle punctuation style to Chinese translations."""
    return (
        text.replace("，", " ")
        .replace(",", " ")
        .replace("。", "")
        .replace(".", "")
    )


class Translator:
    """Select an explicit backend, with the legacy auto mode as an option."""

    # Ordered list of (name, backend_class, env_var_or_check) tuples.
    BACKENDS = [
        ("deepseek", DeepSeekBackend, "DEEPSEEK_API_KEY"),
        ("openai", OpenAIBackend, "OPENAI_API_KEY"),
        ("minimax", MiniMaxBackend, "MINIMAX_API_KEY"),
        ("gemini", GeminiBackend, "GOOGLE_API_KEY"),
        ("groq", GroqBackend, "GROQ_API_KEY"),
        ("ollama", OllamaBackend, "OLLAMA_BASE_URL"),
        ("anthropic", AnthropicBackend, "ANTHROPIC_API_KEY"),
        ("zhipu", ZhipuBackend, "ZHIPU_API_KEY"),
        ("google", GoogleBackend, None),
    ]

    def __init__(
        self,
        backend_name: str | None = None,
        glossary_terms: list[dict] | None = None,
    ):
        self._backend: TranslationBackend | None = None
        if glossary_terms is None:
            glossary_terms = GlossaryStore().enabled_terms()
        self._glossary = GlossaryProtector(glossary_terms)
        selected = (
            backend_name or os.environ.get("TRANSLATION_BACKEND", "openai")
        ).strip().lower()
        if selected == "auto":
            self._select_backend_auto()
        else:
            self._select_backend_by_name(selected)

    @staticmethod
    def _credential_is_configured(value: str) -> bool:
        return bool(value) and not value.lower().startswith("your_")

    def _select_backend_by_name(self, selected: str) -> None:
        """Select exactly the requested backend or fail clearly."""
        matches = [item for item in self.BACKENDS if item[0] == selected]
        if not matches:
            choices = ", ".join(item[0] for item in self.BACKENDS)
            raise ValueError(
                f"Unknown TRANSLATION_BACKEND '{selected}'. Choose: {choices}, auto"
            )

        _name, backend_cls, env_check = matches[0]
        if env_check is None:
            self._backend = backend_cls()
        else:
            credential = os.environ.get(env_check, "").strip()
            if not self._credential_is_configured(credential):
                raise RuntimeError(
                    f"{env_check} is required for TRANSLATION_BACKEND={selected}"
                )
            self._backend = backend_cls(api_key=credential)
        print(f"  [Translator] Using {self._backend.name}")

    def _select_backend_auto(self) -> None:
        """Select the first configured backend for backwards compatibility."""
        for _name, backend_cls, env_check in self.BACKENDS:
            if env_check is None:
                self._backend = backend_cls()
                print(f"  [Translator] Using {self._backend.name} (fallback)")
                return

            key = os.environ.get(env_check, "").strip()
            if self._credential_is_configured(key):
                try:
                    self._backend = backend_cls(api_key=key)
                    print(f"  [Translator] Using {self._backend.name}")
                    return
                except Exception as e:
                    print(f"  [Translator] {backend_cls.__name__} failed: {e}, trying next...")

        self._backend = GoogleBackend()
        print(f"  [Translator] Using {self._backend.name} (final fallback)")

    @property
    def backend_name(self) -> str:
        """Return the name of the active backend."""
        return self._backend.name if self._backend else "None"

    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        """Translate a single text segment."""
        protected, markers = self._glossary.protect(text)
        result = self._backend.translate(protected, source_lang, target_lang)
        result = self._glossary.restore(result, markers)
        if target_lang.lower().startswith("zh"):
            result = _normalize_chinese_punctuation(result)
        return result

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        """Translate multiple text segments in batches."""
        if not texts:
            return []

        all_results = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            protected_batch = []
            expected_markers = []
            for text in batch:
                protected, markers = self._glossary.protect(text)
                protected_batch.append(protected)
                expected_markers.append(markers)
            results = self._backend.translate_batch(
                protected_batch, source_lang, target_lang
            )
            if len(results) != len(batch):
                raise RuntimeError(
                    f"{self.backend_name} returned {len(results)} translations "
                    f"for a batch of {len(batch)}; refusing to create misaligned subtitles"
                )
            results = [
                self._glossary.restore(item, markers)
                for item, markers in zip(results, expected_markers)
            ]
            if target_lang.lower().startswith("zh"):
                results = [_normalize_chinese_punctuation(item) for item in results]
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
                "words": seg.get("words", []),
            })
        return result

    def split_bilingual_segment(
        self, japanese: str, chinese: str, chunk_count: int
    ) -> list[dict[str, str]] | None:
        """Ask the selected backend to align semantic cuts, when supported."""
        splitter = getattr(self._backend, "split_bilingual_segment", None)
        if not callable(splitter):
            return None
        return splitter(japanese, chinese, chunk_count)
