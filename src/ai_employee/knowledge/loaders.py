"""File loaders. Produce page-level text so chunks can keep a page citation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

SUPPORTED_SUFFIXES = frozenset(MIME_TYPES)


class UnsupportedFileTypeError(ValueError):
    """Raised for a file extension the loader does not handle."""


@dataclass(frozen=True)
class Page:
    text: str
    # 1-based, or None for formats without pagination.
    number: int | None


@dataclass(frozen=True)
class LoadedDocument:
    # Where the bytes were read from. For a remote source this is a temporary file.
    path: Path
    # Stable identity of the document at its source; the dedupe key for re-ingestion.
    uri: str
    title: str
    mime_type: str
    content_hash: str
    pages: list[Page]

    @property
    def page_count(self) -> int | None:
        return len(self.pages) if self.pages and self.pages[0].number is not None else None


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_pdf(path: Path) -> list[Page]:
    reader = PdfReader(path)
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(Page(text=text, number=index))
    return pages


def _load_text(path: Path) -> list[Page]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [Page(text=text, number=None)] if text else []


def load(path: Path, *, uri: str | None = None, name: str | None = None) -> LoadedDocument:
    """Read a file into pages. Raises UnsupportedFileTypeError for unknown extensions.

    uri and name let a remote source keep its own identity and file name while the bytes
    are read from a temporary download.
    """
    name = name or path.name
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileTypeError(
            f"{name}: '{suffix}' is not supported (expected one of {sorted(SUPPORTED_SUFFIXES)})"
        )

    pages = _load_pdf(path) if suffix == ".pdf" else _load_text(path)
    return LoadedDocument(
        path=path,
        uri=uri or str(path),
        title=Path(name).stem,
        mime_type=MIME_TYPES[suffix],
        content_hash=_content_hash(path),
        pages=pages,
    )


def discover(root: Path) -> list[Path]:
    """Recursively list supported files under root, or [root] if it is a file."""
    if root.is_file():
        return [root]
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
