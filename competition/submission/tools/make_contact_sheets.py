#!/usr/bin/env python3
"""Create labeled contact sheets for rendered PDF page review."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    args = parse_args()
    source = Path(args.input_dir)
    output = Path(args.output_dir)
    pages = sorted(source.glob("*.png"), key=page_number)
    if not pages:
        raise FileNotFoundError(f"no rendered pages found in {source}")
    output.mkdir(parents=True, exist_ok=True)
    per_sheet = args.columns * args.rows
    for start in range(0, len(pages), per_sheet):
        chunk = pages[start : start + per_sheet]
        sheet = compose(chunk, args.columns, args.rows, args.thumb_width)
        index = start // per_sheet + 1
        sheet.save(output / f"contact-{index:02d}.png")
    print(f"CONTACT_SHEET_PASS pages={len(pages)} sheets={math.ceil(len(pages) / per_sheet)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--thumb-width", type=int, default=360)
    return parser.parse_args()


def page_number(path: Path) -> int:
    suffix = path.stem.rsplit("-", 1)[-1]
    return int(suffix)


def compose(paths: list[Path], columns: int, rows: int, thumb_width: int) -> Image.Image:
    label_height = 28
    margin = 18
    first = Image.open(paths[0])
    thumb_height = round(first.height * thumb_width / first.width)
    cell_width = thumb_width + margin * 2
    cell_height = thumb_height + label_height + margin * 2
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "#E8EEF4")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, path in enumerate(paths):
        page = Image.open(path).convert("RGB")
        resampling = getattr(Image, "Resampling", Image)
        page.thumbnail((thumb_width, thumb_height), resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = column * cell_width + margin
        y = row * cell_height + margin + label_height
        canvas.paste(page, (x, y))
        draw.text((x, margin + row * cell_height), f"Page {page_number(path)}", fill="#17324D", font=font)
    return canvas


if __name__ == "__main__":
    raise SystemExit(main())
