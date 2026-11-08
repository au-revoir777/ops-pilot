"""Load and clean knowledge-base documents.

Documents are Markdown files with YAML front matter:

    ---
    title: Checkout service runbook
    doc_type: runbook            # runbook | architecture | troubleshooting | postmortem | procedure
    services: [checkout]         # may be empty
    owner: commerce-platform     # any extra keys are kept as metadata
    ---
    # Markdown body ...

Malformed files are reported, never silently ingested.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.db.models.knowledge import DocumentType

MAX_DOCUMENT_BYTES = 200_000
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SERVICE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


class DocumentError(ValueError):
    """A knowledge-base file that cannot be ingested."""


@dataclass(frozen=True)
class SourceDocument:
    source: str  # path relative to the knowledge-base root, forward slashes
    title: str
    doc_type: DocumentType
    services: list[str]
    content: str  # cleaned Markdown body
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = "\n".join(
            [self.title, self.doc_type.value, ",".join(self.services), self.content]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class LoadResult:
    documents: list[SourceDocument] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # source -> reason


def clean_text(text: str) -> str:
    """Normalise a Markdown body: newlines, comments, control chars, blank runs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HTML_COMMENT.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_document(source: str, raw: str) -> SourceDocument:
    """Parse one file's text. Raises DocumentError with a human-readable reason."""
    if len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise DocumentError(f"larger than {MAX_DOCUMENT_BYTES} bytes")
    raw = raw.lstrip("﻿")
    match = _FRONT_MATTER.match(raw.replace("\r\n", "\n"))
    if match is None:
        raise DocumentError("missing YAML front matter")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise DocumentError(f"invalid YAML front matter: {exc.__class__.__name__}") from exc
    if not isinstance(meta, dict):
        raise DocumentError("front matter must be a mapping")

    title = meta.pop("title", None)
    if not isinstance(title, str) or not title.strip():
        raise DocumentError("front matter needs a non-empty 'title'")
    try:
        doc_type = DocumentType(meta.pop("doc_type", None))
    except ValueError as exc:
        allowed = ", ".join(t.value for t in DocumentType)
        raise DocumentError(f"'doc_type' must be one of: {allowed}") from exc
    services = meta.pop("services", []) or []
    if not isinstance(services, list) or not all(
        isinstance(s, str) and _SERVICE.match(s) for s in services
    ):
        raise DocumentError("'services' must be a list of lowercase service names")

    content = clean_text(raw.replace("\r\n", "\n")[match.end() :])
    if not content:
        raise DocumentError("document body is empty")

    # Keep remaining front matter as JSON-safe metadata (dates become strings).
    metadata = {str(k): v if isinstance(v, (str, int, float, bool, list)) else str(v)
                for k, v in meta.items()}  # fmt: skip
    return SourceDocument(
        source=source,
        title=title.strip(),
        doc_type=doc_type,
        services=sorted(set(services)),
        content=content,
        metadata=metadata,
    )


def load_documents(root: Path) -> LoadResult:
    """Load every ``*.md`` file under ``root`` (recursively), collecting errors."""
    result = LoadResult()
    if not root.is_dir():
        raise FileNotFoundError(f"knowledge base directory not found: {root}")
    for path in sorted(root.rglob("*.md")):
        source = path.relative_to(root).as_posix()
        try:
            raw = path.read_text(encoding="utf-8")
            result.documents.append(parse_document(source, raw))
        except UnicodeDecodeError:
            result.errors[source] = "not valid UTF-8"
        except DocumentError as exc:
            result.errors[source] = str(exc)
    return result
