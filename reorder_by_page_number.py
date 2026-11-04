#!/usr/bin/env python3
"""OCR bottom-center ~N~ page numbers and rewrite PDF in numeric order."""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageOps
from pypdf import PdfReader, PdfWriter

from paths import PDFS, ensure_pdfs_dir, resolve_pdf

DIGITS_RE = re.compile(r"^\d{1,3}$")
WRAPPED_RE = re.compile(r"^[~\-—–'\"“”]*\s*(\d{1,3})\s*[~\-—–'\"“”]*$")
LOOSE_RE = re.compile(r"(\d{1,3})")


def render_page(page: fitz.Page, scale: float = 3.0) -> Image.Image:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def prepare_band(img: Image.Image) -> Image.Image:
    w, h = img.size
    band = img.crop((0, int(h * 0.84), w, h))
    band = ImageOps.grayscale(band)
    band = ImageEnhance.Contrast(band).enhance(2.4)
    return band.resize((band.width * 2, band.height * 2), Image.Resampling.LANCZOS)


def tokens_from_band(band: Image.Image) -> list[dict]:
    data = pytesseract.image_to_data(
        band,
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    out = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        conf = float(data["conf"][i])
        if conf < 0:
            continue
        out.append(
            {
                "text": txt,
                "conf": conf,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "cx": data["left"][i] + data["width"][i] / 2,
                "cy": data["top"][i] + data["height"][i] / 2,
                "bottom": data["top"][i] + data["height"][i],
            }
        )
    return out


def parse_wrapped(text: str) -> int | None:
    m = WRAPPED_RE.match(text)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 200 else None


def detect_page_number(img: Image.Image) -> tuple[int | None, str]:
    band = prepare_band(img)
    tokens = tokens_from_band(band)
    if not tokens:
        return None, ""

    bw = band.width
    bh = band.height
    center_x = bw / 2

    # Keep tokens in lower 55% of band and near horizontal center
    footer = [
        t
        for t in tokens
        if t["cy"] >= bh * 0.35 and abs(t["cx"] - center_x) <= bw * 0.28
    ]
    if not footer:
        footer = [t for t in tokens if abs(t["cx"] - center_x) <= bw * 0.22]

    candidates: list[tuple[float, int, str]] = []  # (score, number, evidence)

    # 1) Single token that is / contains ~N~
    for t in footer:
        n = parse_wrapped(t["text"])
        if n is None:
            # OCR sometimes glues garbage: "-279~" for 29, "086" etc.
            m = re.search(r"[~\-—]\s*(\d{1,3})\s*[~\-—]", t["text"])
            if m:
                n = int(m.group(1))
                if not (1 <= n <= 200):
                    n = None
        if n is not None:
            # Prefer lower on page, nearer center, higher confidence
            score = (
                (t["bottom"] / bh) * 3.0
                + (1.0 - abs(t["cx"] - center_x) / (bw / 2)) * 2.0
                + min(t["conf"], 100) / 100.0
            )
            # Penalize unlikely 3-digit page numbers for this booklet
            if n >= 100:
                score -= 2.0
            candidates.append((score, n, t["text"]))

    # 2) Assemble ~ + digits + ~ from neighboring tokens
    footer_sorted = sorted(footer, key=lambda t: t["left"])
    for i, t in enumerate(footer_sorted):
        if not DIGITS_RE.match(t["text"]):
            continue
        n = int(t["text"])
        if not (1 <= n <= 200):
            continue
        # look for tilde-like neighbors within a small gap
        left_ok = right_ok = False
        for u in footer_sorted:
            if u is t:
                continue
            gap_l = t["left"] - (u["left"] + u["width"])
            gap_r = u["left"] - (t["left"] + t["width"])
            if 0 <= gap_l <= t["height"] * 2.5 and re.search(r"[~\-—–]", u["text"]):
                left_ok = True
            if 0 <= gap_r <= t["height"] * 2.5 and re.search(r"[~\-—–]", u["text"]):
                right_ok = True
        if left_ok or right_ok:
            score = (
                (t["bottom"] / bh) * 3.0
                + (1.0 - abs(t["cx"] - center_x) / (bw / 2)) * 2.0
                + min(t["conf"], 100) / 100.0
                + (1.5 if left_ok and right_ok else 0.5)
            )
            if n >= 100:
                score -= 2.0
            evidence = f"{'~' if left_ok else ''}{n}{'~' if right_ok else ''}"
            candidates.append((score, n, evidence))

    if candidates:
        candidates.sort(reverse=True)
        best = candidates[0]
        evidence = ", ".join(f"{n}:{e}@{s:.2f}" for s, n, e in candidates[:4])
        return best[1], evidence

    # 3) Fallback: lowest centered digit-only token
    digit_tokens = [
        t for t in footer if DIGITS_RE.match(t["text"]) and 1 <= int(t["text"]) <= 200
    ]
    if digit_tokens:
        digit_tokens.sort(
            key=lambda t: (
                t["bottom"],
                -abs(t["cx"] - center_x),
                t["conf"],
            ),
            reverse=True,
        )
        t = digit_tokens[0]
        # Only accept if quite centered and fairly low
        if abs(t["cx"] - center_x) <= bw * 0.15 and t["cy"] >= bh * 0.45:
            return int(t["text"]), f"fallback:{t['text']}"

    sample = " ".join(t["text"] for t in sorted(footer, key=lambda t: t["left"])[:12])
    return None, sample


def default_out(src: Path) -> Path:
    stem = src.stem.removesuffix("_halves")
    return src.with_name(f"{stem}_ordered.pdf")


def main() -> int:
    ensure_pdfs_dir()
    parser = argparse.ArgumentParser(
        description="OCR footer page numbers and rewrite the PDF in numeric order. "
        f"PDFs are read from / written to {PDFS.name}/ by default."
    )
    parser.add_argument(
        "pdf",
        help=f"Input PDF filename or path (default folder: {PDFS.name}/)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output PDF (default: pdfs/<stem>_ordered.pdf)",
    )
    args = parser.parse_args()

    pdf = resolve_pdf(args.pdf)
    out = resolve_pdf(args.output, must_exist=False) if args.output else default_out(pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = out.with_name(f"{out.stem}_report.txt")

    doc = fitz.open(str(pdf))
    reader = PdfReader(str(pdf))
    n_pages = len(doc)
    print(f"Scanning {n_pages} pages for footer numbers...", flush=True)

    detected: list[tuple[int, int | None, str]] = []
    for i in range(n_pages):
        img = render_page(doc[i])
        num, debug = detect_page_number(img)
        detected.append((i, num, debug))
        print(f"  pdf[{i:02d}] -> {num if num is not None else '?'}", flush=True)

    numbered = [(i, num) for i, num, _ in detected if num is not None]
    unnumbered = [i for i, num, _ in detected if num is None]

    by_num: dict[int, list[int]] = {}
    for i, num in numbered:
        by_num.setdefault(num, []).append(i)
    dupes = {n: idxs for n, idxs in by_num.items() if len(idxs) > 1}

    ordered_indices: list[int] = list(unnumbered)
    for num in sorted(by_num):
        ordered_indices.extend(by_num[num])

    writer = PdfWriter()
    for i in ordered_indices:
        writer.add_page(reader.pages[i])
    with open(out, "wb") as f:
        writer.write(f)

    nums = sorted(by_num)
    missing = [n for n in range(nums[0], nums[-1] + 1) if n not in by_num] if nums else []

    lines = [
        f"source: {pdf.name}",
        f"output: {out.name}",
        f"total pages: {n_pages}",
        f"numbered: {len(numbered)}",
        f"unnumbered (kept at front, scan order): {unnumbered}",
        f"duplicates: {dupes or 'none'}",
        f"page number range: {nums[0] if nums else 'n/a'}–{nums[-1] if nums else 'n/a'}",
        f"missing in range: {missing or 'none'}",
        "",
        "detection detail:",
    ]
    for i, num, debug in detected:
        lines.append(f"  pdf[{i:02d}] number={num!s:4}  {debug}")
    lines.append("")
    lines.append("final order:")
    num_lookup = {i: num for i, num, _ in detected}
    for new_pos, i in enumerate(ordered_indices):
        lines.append(f"  out[{new_pos:02d}] <- pdf[{i:02d}]  #{num_lookup[i]}")

    report.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {len(writer.pages)} pages -> {out}", flush=True)
    print(f"Report -> {report}", flush=True)
    if dupes:
        print(f"WARNING duplicates: {dupes}", flush=True)
    if unnumbered:
        print(f"Unnumbered first: {unnumbered}", flush=True)
    if missing:
        print(f"Missing in range: {missing}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
