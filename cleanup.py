#!/usr/bin/env python3
"""Remove intermediate files from a split/reorder run."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from paths import PDFS, ROOT

# Always-safe junk from this toolkit
LOGS = [
    "reorder_ui.log",
    "reorder_run.log",
    "page_number_report.txt",
]

# Intermediate PDF name suffixes (source PDFs without these are kept)
INTERMEDIATE_SUFFIXES = (
    "_halves.pdf",
    "_ordered.pdf",
    "_reordered.pdf",
)


def iter_pdf_dirs() -> list[Path]:
    dirs = [ROOT]
    if PDFS.exists():
        dirs.append(PDFS)
    return dirs


def collect_targets(args: argparse.Namespace) -> list[Path]:
    targets: list[Path] = []

    if args.thumbs or args.all:
        thumbs = ROOT / "thumbs"
        if thumbs.exists():
            targets.append(thumbs)

    if args.logs or args.all:
        for name in LOGS:
            p = ROOT / name
            if p.exists():
                targets.append(p)

    if args.intermediates or args.all:
        for folder in iter_pdf_dirs():
            for p in sorted(folder.glob("*.pdf")):
                if any(p.name.endswith(sfx) for sfx in INTERMEDIATE_SUFFIXES):
                    if p not in targets:
                        targets.append(p)

    if args.stem:
        stem = args.stem
        for folder in iter_pdf_dirs():
            for sfx in INTERMEDIATE_SUFFIXES:
                p = folder / f"{stem}{sfx}"
                if p.exists() and p not in targets:
                    targets.append(p)

    return targets


def main():
    parser = argparse.ArgumentParser(
        description="Clean thumbs, logs, and/or intermediate PDFs "
        f"(searches {PDFS.name}/ and project root)."
    )
    parser.add_argument(
        "--thumbs",
        action="store_true",
        help="Delete the thumbs/ folder",
    )
    parser.add_argument(
        "--logs",
        action="store_true",
        help="Delete reorder logs and page_number_report.txt",
    )
    parser.add_argument(
        "--intermediates",
        action="store_true",
        help="Delete all *_halves / *_ordered / *_reordered PDFs",
    )
    parser.add_argument(
        "--stem",
        help="Only delete intermediates for this stem "
        "(e.g. Owning_The_Art_of_Production)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete thumbs, logs, and all intermediate PDFs",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    args = parser.parse_args()

    if not (args.thumbs or args.logs or args.intermediates or args.all or args.stem):
        parser.error("Pick at least one of: --thumbs --logs --intermediates --stem --all")

    targets = collect_targets(args)
    if not targets:
        print("Nothing to clean.")
        return

    for t in targets:
        kind = "dir" if t.is_dir() else "file"
        action = "Would remove" if args.dry_run else "Removing"
        try:
            rel = t.relative_to(ROOT)
        except ValueError:
            rel = t
        print(f"{action} {kind}: {rel}")
        if args.dry_run:
            continue
        if t.is_dir():
            shutil.rmtree(t)
        else:
            t.unlink()

    if args.dry_run:
        print("(dry run — nothing deleted)")
    else:
        print("Done.")


if __name__ == "__main__":
    main()
