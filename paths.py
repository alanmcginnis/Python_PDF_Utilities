#!/usr/bin/env python3
"""Shared paths: PDFs live in pdfs/ so the project root stays tidy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
PDFS = ROOT / "pdfs"


def ensure_pdfs_dir() -> Path:
    PDFS.mkdir(parents=True, exist_ok=True)
    return PDFS


def resolve_pdf(name: str | Path, *, must_exist: bool = True) -> Path:
    """
    Resolve a PDF path.

    Bare filenames (e.g. scan.pdf) are looked up in pdfs/, then the project
    root. Paths with a directory component or absolute paths are used as-is
    (relative to the project root if not absolute).
    """
    path = Path(name)
    if path.is_absolute():
        candidates = [path]
    elif path.parent != Path("."):
        candidates = [ROOT / path, path]
    else:
        candidates = [PDFS / path.name, ROOT / path.name]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    if must_exist:
        hint = PDFS / path.name
        raise SystemExit(f"Not found: {name}\n  Put PDFs in: {PDFS}/\n  Expected: {hint}")

    # Prefer writing into pdfs/ for bare names
    if path.is_absolute():
        return path
    if path.parent != Path("."):
        return (ROOT / path).resolve()
    ensure_pdfs_dir()
    return (PDFS / path.name).resolve()


def sibling_out(src: Path, suffix: str) -> Path:
    """Build an output next to src, e.g. book.pdf -> book_halves.pdf."""
    return src.with_name(f"{src.stem}{suffix}")
