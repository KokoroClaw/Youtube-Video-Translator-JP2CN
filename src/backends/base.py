"""
Base translator backend interface.
"""

from abc import ABC, abstractmethod
from typing import Any


class TranslationBackend(ABC):
    """Abstract base class for translation backends."""

    def __init__(self, api_key: str | None = None, **kwargs):
        """
        Initialize the backend.

        Args:
            api_key: API key for the service (may be None for local backends).
            **kwargs: Additional backend-specific configuration.
        """
        self.api_key = api_key
        self._config = kwargs

    @abstractmethod
    def translate(self, text: str, source_lang: str = "ja", target_lang: str = "zh") -> str:
        """
        Translate a single text segment.

        Args:
            text: Text to translate.
            source_lang: Source language code.
            target_lang: Target language code.

        Returns:
            Translated text.
        """
        ...

    @abstractmethod
    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ja",
        target_lang: str = "zh"
    ) -> list[str]:
        """
        Translate multiple text segments at once.

        Args:
            texts: List of texts to translate.
            source_lang: Source language code.
            target_lang: Target language code.

        Returns:
            List of translated texts (same order).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...
