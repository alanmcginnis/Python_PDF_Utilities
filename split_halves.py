#!/usr/bin/env python3
"""Split each PDF page into left and right halves (in that order)."""

from __future__ import annotations

import argparse
from copy import deepcopy

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from paths import PDFS, ensure_pdfs_dir, resolve_pdf, sibling_out


def split_page_vertically(page):
    """Return (left_half, right_half) as cropped page copies."""
    box = page.mediabox
    left = float(box.left)
    right = float(box.right)
    bottom = float(box.bottom)
    top = float(box.top)
    mid = (left + right) / 2

    left_page = deepcopy(page)
    right_page = deepcopy(page)

    left_page.mediabox = RectangleObject((left, bottom, mid, top))
    left_page.cropbox = RectangleObject((left, bottom, mid, top))

    right_page.mediabox = RectangleObject((mid, bottom, right, top))
    right_page.cropbox = RectangleObject((mid, bottom, right, top))

    return left_page, right_page


def main():
    ensure_pdfs_dir()
    parser = argparse.ArgumentParser(
        description="Split each page of a PDF into left then right halves. "
        f"PDFs are read from / written to {PDFS.name}/ by default."
    )
    parser.add_argument(
        "pdf",
        help=f"Input PDF filename or path (default folder: {PDFS.name}/)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output PDF (default: pdfs/<stem>_halves.pdf)",
    )
    args = parser.parse_args()

    src = resolve_pdf(args.pdf)
    out = resolve_pdf(args.output, must_exist=False) if args.output else sibling_out(src, "_halves.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(src))
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        left, right = split_page_vertically(page)
        writer.add_page(left)
        writer.add_page(right)
        print(f"Split page {i + 1}/{len(reader.pages)}")

    with open(out, "wb") as f:
        writer.write(f)

    print(f"Wrote {len(writer.pages)} pages -> {out}")


if __name__ == "__main__":
    main()
