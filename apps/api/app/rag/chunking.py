"""Heading-aware Markdown chunking.

Strategy:
  1. Split the document into sections at Markdown headings (#, ##, ###), keeping
     the heading trail ("Checkout service runbook > Mitigation") for provenance.
  2. Inside a section, pack whole paragraphs (blank-line separated) into a chunk
     while it stays within ``max_words``.
  3. A paragraph longer than ``max_words`` is cut into windows of ``max_words``
     that overlap by ``overlap`` words.
  4. Every chunk after the first in a section starts with the last ``overlap``
     words of the previous one, so a fact spanning a boundary is retrievable
     from either side. A chunk is therefore at most ``max_words + overlap`` words.

Sizes are counted in words (whitespace tokens), not model tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    index: int
    section: str
    content: str

    @property
    def word_count(self) -> int:
        return len(self.content.split())

    def embedding_text(self, title: str) -> str:
        """Text sent to the embedder: the heading trail adds topical context."""
        trail = self.section if self.section.startswith(title) else f"{title} > {self.section}"
        return f"{trail}\n\n{self.content}"


def split_sections(text: str, title: str) -> list[tuple[str, str]]:
    """Return (heading trail, body) pairs; text before the first heading uses the title."""
    trail: list[str] = []
    sections: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((" > ".join(trail) or title, body))
        buffer.clear()

    for line in text.split("\n"):
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            trail[:] = [*trail[: level - 1], match.group(2).strip()]
        else:
            buffer.append(line)
    flush()
    return sections


def _pack(paragraphs: list[str], max_words: int, overlap: int) -> list[tuple[str, bool]]:
    """Group paragraphs into pieces. Returns (text, starts_with_own_overlap)."""
    pieces: list[tuple[str, bool]] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current_words
        if current:
            pieces.append(("\n\n".join(current), False))
            current.clear()
            current_words = 0

    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > max_words:
            flush()
            step = max_words - overlap
            for n, start in enumerate(range(0, max(len(words) - overlap, 1), step)):
                pieces.append((" ".join(words[start : start + max_words]), n > 0))
            continue
        if current_words + len(words) > max_words:
            flush()
        current.append(" ".join(words))
        current_words += len(words)
    flush()
    return pieces


def chunk_markdown(text: str, title: str, max_words: int, overlap: int) -> list[Chunk]:
    if max_words <= 0 or not 0 <= overlap < max_words:
        raise ValueError("require max_words > 0 and 0 <= overlap < max_words")

    chunks: list[Chunk] = []
    for section, body in split_sections(text, title):
        paragraphs = [p.strip() for p in _PARAGRAPH_BREAK.split(body) if p.strip()]
        previous = ""
        for piece, has_overlap in _pack(paragraphs, max_words, overlap):
            content = piece
            if previous and overlap and not has_overlap:
                tail = " ".join(previous.split()[-overlap:])
                content = f"{tail}\n\n{piece}"
            chunks.append(Chunk(index=len(chunks), section=section, content=content))
            previous = piece
    return chunks
