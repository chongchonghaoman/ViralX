#!/usr/bin/env python3
"""Generate the ViralX hero title as SVG outlines without embedding a font.

The input font is only used at build time. The emitted SVG files contain glyph
paths, not a font program, so the source TTF must never be copied into the repo
or deployed with the website. Install the pinned development dependency with
``python -m pip install -r requirements-dev.txt`` before regenerating the art.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont


TITLE = "把爆款拆到每一秒"
WIDE_LINES = (TITLE,)
STACKED_LINES = ("把爆款拆到", "每一秒")
INK = "#0F0F0F"
TRACKING = 12
PADDING = 36
STACKED_GAP = 126


@dataclass(frozen=True)
class GlyphPath:
    path: str
    x: int


@dataclass(frozen=True)
class LineLayout:
    glyphs: tuple[GlyphPath, ...]
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


def layout_line(font: TTFont, text: str) -> LineLayout:
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"].metrics
    cursor = 0
    glyphs: list[GlyphPath] = []
    bounds: list[tuple[float, float, float, float]] = []

    for index, character in enumerate(text):
        glyph_name = cmap.get(ord(character))
        if glyph_name is None:
            raise ValueError(f"Missing glyph for {character!r} (U+{ord(character):04X})")

        glyph = glyph_set[glyph_name]
        path_pen = SVGPathPen(glyph_set)
        glyph.draw(path_pen)
        glyphs.append(GlyphPath(path=path_pen.getCommands(), x=cursor))

        bounds_pen = BoundsPen(glyph_set)
        glyph.draw(bounds_pen)
        if bounds_pen.bounds is not None:
            x_min, y_min, x_max, y_max = bounds_pen.bounds
            bounds.append((cursor + x_min, y_min, cursor + x_max, y_max))

        cursor += hmtx[glyph_name][0]
        if index < len(text) - 1:
            cursor += TRACKING

    if not bounds:
        raise ValueError(f"No drawable outlines found for {text!r}")

    return LineLayout(
        glyphs=tuple(glyphs),
        min_x=min(item[0] for item in bounds),
        min_y=min(item[1] for item in bounds),
        max_x=max(item[2] for item in bounds),
        max_y=max(item[3] for item in bounds),
    )


def svg_document(font: TTFont, lines: tuple[str, ...], description: str) -> str:
    layouts = tuple(layout_line(font, line) for line in lines)
    art_width = max(line.width for line in layouts)
    art_height = sum(line.height for line in layouts) + STACKED_GAP * (len(layouts) - 1)
    view_width = round(art_width + PADDING * 2)
    view_height = round(art_height + PADDING * 2)

    paths: list[str] = []
    top = float(PADDING)
    for layout in layouts:
        line_left = PADDING + (art_width - layout.width) / 2
        translate_x = line_left - layout.min_x
        baseline_y = top + layout.max_y
        for glyph in layout.glyphs:
            transform = (
                f"translate({translate_x + glyph.x:.2f} {baseline_y:.2f}) scale(1 -1)"
            )
            paths.append(f'    <path d="{glyph.path}" transform="{transform}"/>')
        top += layout.height + STACKED_GAP

    font_name = font["name"].getDebugName(4) or "supplied typeface"
    path_markup = "\n".join(paths)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_width} {view_height}" width="{view_width}" height="{view_height}" fill="{INK}">
  <title>{escape(TITLE)}</title>
  <desc>{escape(description)} Generated from {escape(font_name)} as outlined artwork; no font program is embedded.</desc>
  <g aria-hidden="true">
{path_markup}
  </g>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, required=True, help="Licensed local source TTF")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    font = TTFont(args.font)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "viralx-title-shuei-wide.svg": (WIDE_LINES, "Single-line ViralX homepage claim."),
        "viralx-title-shuei-stacked.svg": (STACKED_LINES, "Two-line ViralX homepage claim for narrow screens."),
    }
    for filename, (lines, description) in outputs.items():
        destination = args.out_dir / filename
        destination.write_text(svg_document(font, lines, description), encoding="utf-8")
        print(destination)


if __name__ == "__main__":
    main()
