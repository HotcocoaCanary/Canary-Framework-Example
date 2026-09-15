"""Text splitting — turn a document into retrievable passages.

Splitting happens on natural boundaries first (blank lines, then sentence-ending
punctuation in both Chinese and Latin scripts) and only falls back to a hard cut
when a single sentence is longer than the window.  Consecutive chunks overlap by
``chunk_overlap`` characters so an answer that straddles a boundary is still
retrievable from at least one passage.
"""

from __future__ import annotations

import re

from canary_framework import cocoa
from config import AppConfig

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[。！？!?；;])|(?<=[.!?])\s+")


@cocoa(deps=[AppConfig])
class TextChunker:
    app_config: AppConfig

    def split(self, text: str) -> list[str]:
        size = max(self.app_config.chunk_size, 1)
        overlap = min(max(self.app_config.chunk_overlap, 0), size - 1)

        chunks: list[str] = []
        buffer = ""
        for unit in self._units(text, size):
            if buffer and len(buffer) + len(unit) > size:
                chunks.append(buffer.strip())
                buffer = buffer[-overlap:] if overlap else ""
            buffer += unit
        if buffer.strip():
            chunks.append(buffer.strip())
        return [c for c in chunks if c]

    def _units(self, text: str, size: int) -> list[str]:
        """Atoms to pack into chunks: sentences, hard-cut when oversized."""
        units: list[str] = []
        for paragraph in _PARAGRAPH.split(text or ""):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            for sentence in _SENTENCE.split(paragraph):
                if not sentence:
                    continue
                while len(sentence) > size:
                    units.append(sentence[:size])
                    sentence = sentence[size:]
                if sentence:
                    units.append(sentence)
            units.append("\n")
        return units
