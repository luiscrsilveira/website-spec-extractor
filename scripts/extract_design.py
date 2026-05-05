#!/usr/bin/env python3
"""
extract_design.py — Extract design tokens from crawled CSS.

Reads every CSS file in <crawl_dir>/assets/css/ plus inline <style> blocks
from <crawl_dir>/pages/*.html, then aggregates:

  - colors (hex, rgb, rgba, hsl)
  - font families
  - font sizes
  - spacing values (margin, padding, gap)
  - border radii
  - media query breakpoints

Writes design_tokens.json to <crawl_dir>/.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

# -- Regex patterns -----------------------------------------------------------

HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_COLOR_RE = re.compile(r"rgba?\([^)]+\)")
HSL_COLOR_RE = re.compile(r"hsla?\([^)]+\)")
NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "orange",
    "purple", "pink", "gray", "grey", "transparent",
}

# Match `property: value;` declarations
DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;{}]+)\s*;")
MEDIA_QUERY_RE = re.compile(r"@media[^{]*\(\s*(?:min|max)-width\s*:\s*([\d.]+)(px|em|rem)\s*\)")

SPACING_PROPERTIES = {
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "gap", "row-gap", "column-gap",
}
FONT_SIZE_PROPS = {"font-size"}
FONT_FAMILY_PROPS = {"font-family", "font"}
RADIUS_PROPS = {
    "border-radius",
    "border-top-left-radius", "border-top-right-radius",
    "border-bottom-left-radius", "border-bottom-right-radius",
}
COLOR_PROPS = {
    "color", "background", "background-color", "border", "border-color",
    "border-top-color", "border-right-color", "border-bottom-color",
    "border-left-color", "fill", "stroke", "outline", "outline-color",
    "box-shadow", "text-shadow",
}


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def normalize_hex(c: str) -> str:
    """Normalize 3-digit hex to 6-digit, lowercase."""
    c = c.lower()
    if len(c) == 4:  # #abc -> #aabbcc
        return "#" + "".join(ch * 2 for ch in c[1:])
    if len(c) == 5:  # #abcd -> #aabbccdd
        return "#" + "".join(ch * 2 for ch in c[1:])
    return c


def extract_colors(css: str) -> Counter:
    counter: Counter = Counter()
    for m in HEX_COLOR_RE.finditer(css):
        counter[normalize_hex(m.group(0))] += 1
    for m in RGB_COLOR_RE.finditer(css):
        counter[m.group(0).replace(" ", "")] += 1
    for m in HSL_COLOR_RE.finditer(css):
        counter[m.group(0).replace(" ", "")] += 1
    # Named colors — only count when on word boundary and inside a likely color context
    for name in NAMED_COLORS:
        for m in re.finditer(rf"\b{name}\b", css, flags=re.IGNORECASE):
            counter[name.lower()] += 1
    return counter


def extract_declarations(css: str) -> list[tuple[str, str]]:
    return [(prop.strip().lower(), value.strip()) for prop, value in DECL_RE.findall(css)]


def value_tokens(value: str) -> list[str]:
    """Split a CSS value like '8px 16px' into individual tokens."""
    return [t for t in re.split(r"\s+", value.strip()) if t]


def is_length(token: str) -> bool:
    return bool(re.fullmatch(r"-?\d*\.?\d+(?:px|em|rem|%|vh|vw|vmin|vmax)", token))


def extract_breakpoints(css: str) -> Counter:
    counter: Counter = Counter()
    for m in MEDIA_QUERY_RE.finditer(css):
        counter[f"{m.group(1)}{m.group(2)}"] += 1
    return counter


def extract_font_families(value: str) -> list[str]:
    """Pull comma-separated family names from a font-family or font shorthand."""
    # Strip url(...) and other functions to be safe
    cleaned = re.sub(r"\b(?:url|var|calc)\([^)]*\)", "", value)
    families = []
    for raw in cleaned.split(","):
        family = raw.strip().strip('"').strip("'")
        # In `font` shorthand, the family is at the end after size — be lenient
        if not family or family in {"inherit", "initial", "unset"}:
            continue
        # Filter out things that look like sizes/weights
        if re.fullmatch(r"\d+(?:\.\d+)?(?:px|em|rem|%)?", family):
            continue
        if family.lower() in {"normal", "bold", "italic", "oblique", "lighter", "bolder"}:
            continue
        families.append(family)
    return families


def gather_css_text(crawl_dir: Path) -> str:
    parts: list[str] = []

    css_dir = crawl_dir / "assets" / "css"
    if css_dir.exists():
        for css_file in sorted(css_dir.glob("*.css")):
            parts.append(f"/* SOURCE: {css_file.name} */\n")
            parts.append(css_file.read_text(encoding="utf-8", errors="replace"))

    pages_dir = crawl_dir / "pages"
    if pages_dir.exists():
        for html_file in sorted(pages_dir.glob("*.html")):
            html = html_file.read_text(encoding="utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            for style in soup.find_all("style"):
                if style.string:
                    parts.append(f"/* INLINE: {html_file.name} */\n")
                    parts.append(style.string)

    return "\n".join(parts)


def analyze(css: str) -> dict:
    css = strip_comments(css)
    declarations = extract_declarations(css)

    colors = Counter()
    font_sizes: Counter = Counter()
    font_families: Counter = Counter()
    spacing: Counter = Counter()
    radii: Counter = Counter()

    for prop, value in declarations:
        # Colors — extract from any property whose value plausibly contains a color
        if prop in COLOR_PROPS or "color" in prop or "background" in prop or "shadow" in prop or "border" in prop:
            for hex_match in HEX_COLOR_RE.finditer(value):
                colors[normalize_hex(hex_match.group(0))] += 1
            for rgb_match in RGB_COLOR_RE.finditer(value):
                colors[rgb_match.group(0).replace(" ", "")] += 1
            for hsl_match in HSL_COLOR_RE.finditer(value):
                colors[hsl_match.group(0).replace(" ", "")] += 1

        if prop in FONT_SIZE_PROPS:
            for tok in value_tokens(value):
                if is_length(tok):
                    font_sizes[tok] += 1
                    break  # font-size has one length value

        if prop in FONT_FAMILY_PROPS:
            for fam in extract_font_families(value):
                font_families[fam] += 1

        if prop in SPACING_PROPERTIES:
            for tok in value_tokens(value):
                if is_length(tok) and tok != "0":
                    spacing[tok] += 1

        if prop in RADIUS_PROPS:
            for tok in value_tokens(value):
                if is_length(tok):
                    radii[tok] += 1

    # Also a global color sweep so we don't miss colors used in unusual properties
    global_colors = extract_colors(css)
    for c, n in global_colors.items():
        colors[c] = max(colors[c], n)

    breakpoints = extract_breakpoints(css)

    def sort_by_freq(c: Counter, limit: int | None = None) -> list[dict]:
        items = [{"value": v, "count": n} for v, n in c.most_common(limit)]
        return items

    def sort_lengths(c: Counter) -> list[dict]:
        def length_key(item):
            v = item[0]
            m = re.match(r"(-?\d*\.?\d+)(px|em|rem|%|vh|vw|vmin|vmax)", v)
            if not m:
                return (999, v)
            num = float(m.group(1))
            unit_order = {"px": 0, "rem": 1, "em": 2, "%": 3, "vh": 4, "vw": 5, "vmin": 6, "vmax": 7}
            return (unit_order.get(m.group(2), 99), num)
        items = sorted(c.items(), key=length_key)
        return [{"value": v, "count": n} for v, n in items]

    return {
        "colors": sort_by_freq(colors, limit=80),
        "font_families": sort_by_freq(font_families),
        "font_sizes": sort_lengths(font_sizes),
        "spacing": sort_lengths(spacing),
        "border_radius": sort_lengths(radii),
        "breakpoints": sort_lengths(breakpoints),
        "totals": {
            "unique_colors": len(colors),
            "unique_font_families": len(font_families),
            "unique_font_sizes": len(font_sizes),
            "unique_spacing_values": len(spacing),
        },
    }


def main():
    p = argparse.ArgumentParser(description="Extract design tokens from crawled CSS.")
    p.add_argument("--crawl-dir", required=True, type=Path)
    args = p.parse_args()

    css = gather_css_text(args.crawl_dir)
    if not css.strip():
        print("No CSS found — writing empty design_tokens.json", file=__import__("sys").stderr)
        empty = {
            "colors": [], "font_families": [], "font_sizes": [],
            "spacing": [], "border_radius": [], "breakpoints": [],
            "totals": {"unique_colors": 0, "unique_font_families": 0,
                       "unique_font_sizes": 0, "unique_spacing_values": 0},
        }
        out = args.crawl_dir / "design_tokens.json"
        out.write_text(json.dumps(empty, indent=2), encoding="utf-8")
        return

    tokens = analyze(css)

    out = args.crawl_dir / "design_tokens.json"
    out.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"  colors:   {tokens['totals']['unique_colors']} unique")
    print(f"  fonts:    {tokens['totals']['unique_font_families']} families")
    print(f"  sizes:    {tokens['totals']['unique_font_sizes']} font-sizes")
    print(f"  spacing:  {tokens['totals']['unique_spacing_values']} values")


if __name__ == "__main__":
    main()
