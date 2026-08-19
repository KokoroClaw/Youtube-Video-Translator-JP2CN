"""Persistent glossary storage and protected-term translation helpers."""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any


DEFAULT_GLOSSARY_PATH = Path(__file__).parent.parent / "data" / "glossary.json"


class GlossaryStore:
    """Thread-safe JSON glossary with atomic writes."""

    def __init__(self, path: Path | str = DEFAULT_GLOSSARY_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list_terms(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Glossary file must contain a JSON array")
            return payload

    def enabled_terms(self) -> list[dict[str, Any]]:
        return [term for term in self.list_terms() if term.get("enabled", True)]

    def add_term(
        self, source: str, target: str, note: str = "", enabled: bool = True
    ) -> dict[str, Any]:
        with self._lock:
            terms = self.list_terms()
            source = source.strip()
            target = target.strip()
            self._validate(source, target, terms)
            term = {
                "id": uuid.uuid4().hex,
                "source": source,
                "target": target,
                "note": note.strip(),
                "enabled": bool(enabled),
            }
            terms.append(term)
            self._write(terms)
            return term

    def update_term(self, term_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            terms = self.list_terms()
            index = next((i for i, term in enumerate(terms) if term["id"] == term_id), -1)
            if index < 0:
                raise KeyError(term_id)
            current = terms[index]
            updated = {
                **current,
                **{key: value for key, value in changes.items() if key in {"source", "target", "note", "enabled"}},
            }
            updated["source"] = str(updated["source"]).strip()
            updated["target"] = str(updated["target"]).strip()
            updated["note"] = str(updated.get("note", "")).strip()
            updated["enabled"] = bool(updated.get("enabled", True))
            self._validate(updated["source"], updated["target"], terms, exclude_id=term_id)
            terms[index] = updated
            self._write(terms)
            return updated

    def delete_term(self, term_id: str) -> None:
        with self._lock:
            terms = self.list_terms()
            filtered = [term for term in terms if term["id"] != term_id]
            if len(filtered) == len(terms):
                raise KeyError(term_id)
            self._write(filtered)

    @staticmethod
    def _validate(
        source: str,
        target: str,
        terms: list[dict[str, Any]],
        exclude_id: str | None = None,
    ) -> None:
        if not source or not target:
            raise ValueError("日文原词和中文译法不能为空")
        if "__GLOSSARY_" in source or "__GLOSSARY_" in target:
            raise ValueError("术语中不能包含保留标记 __GLOSSARY_")
        if any(term["source"] == source and term["id"] != exclude_id for term in terms):
            raise ValueError(f"日文术语已存在：{source}")

    def _write(self, terms: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(terms, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class GlossaryProtector:
    """Replace matched source terms with markers and restore fixed translations."""

    def __init__(self, terms: list[dict[str, Any]] | None = None):
        active = [term for term in (terms or []) if term.get("enabled", True)]
        active.sort(key=lambda term: len(term["source"]), reverse=True)
        self._marker_targets = {
            f"__GLOSSARY_{index}__": term["target"]
            for index, term in enumerate(active)
        }
        self._source_markers = {
            term["source"]: marker
            for marker, term in zip(self._marker_targets, active)
        }
        self._pattern = (
            re.compile("|".join(re.escape(source) for source in self._source_markers))
            if self._source_markers
            else None
        )

    @property
    def active(self) -> bool:
        return self._pattern is not None

    def protect(self, text: str) -> tuple[str, set[str]]:
        if not self._pattern:
            return text, set()
        markers: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            marker = self._source_markers[match.group(0)]
            markers.add(marker)
            return marker

        return self._pattern.sub(replace, text), markers

    def restore(self, text: str, expected_markers: set[str]) -> str:
        missing = [marker for marker in expected_markers if marker not in text]
        if missing:
            raise RuntimeError(
                "翻译结果丢失了术语保护标记：" + ", ".join(sorted(missing))
            )
        for marker, target in self._marker_targets.items():
            text = text.replace(marker, target)
        return text
