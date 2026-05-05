#!/usr/bin/env python3
"""
build_spec.py — Assemble the final spec.md from crawler artifacts.

Reads:
  <crawl_dir>/crawl_index.json
  <crawl_dir>/design_tokens.json
  <crawl_dir>/components.json
  <crawl_dir>/pages/*.html  (for content extraction)

Writes a single markdown spec to --output. The spec is structured as a brief
for a redesigner: it preserves IA, copy, and brand intent while leaving room
for visual improvements.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"Required artifact missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


EMPTY_TOKENS = {
    "colors": [], "font_families": [], "font_sizes": [],
    "spacing": [], "border_radius": [], "breakpoints": [],
    "totals": {"unique_colors": 0, "unique_font_families": 0,
               "unique_font_sizes": 0, "unique_spacing_values": 0},
}
EMPTY_COMPONENTS = {
    "per_page": {},
    "catalog": {
        "header": {"pages": [], "samples": []},
        "nav": {"pages": [], "samples": []},
        "footer": {"pages": [], "samples": []},
        "hero": {"pages": [], "samples": []},
        "cards": [], "forms": [], "ctas": [],
    },
}


def section_for_url(url: str, base_domain: str) -> str:
    """Group URLs by first path segment, normalizing .html away."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return "Home"
    first = parts[0]
    # Strip extensions so /services.html and /services/foo group together
    if "." in first:
        first = first.rsplit(".", 1)[0]
    if first in ("index", ""):
        return "Home"
    return first.replace("-", " ").replace("_", " ").title()


def extract_page_content(html: str) -> dict:
    """Pull headings, paragraphs, image alts, and meta from a page."""
    soup = BeautifulSoup(html, "html.parser")

    # Strip noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()

    og_title = ""
    ogt = soup.find("meta", attrs={"property": "og:title"})
    if ogt and ogt.get("content"):
        og_title = ogt["content"].strip()

    headings: list[dict] = []
    for level in range(1, 5):
        for h in soup.find_all(f"h{level}"):
            text = h.get_text(" ", strip=True)
            if text:
                headings.append({"level": level, "text": text})

    paragraphs: list[str] = []
    main = soup.find("main") or soup.body or soup
    for p in main.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) >= 20:
            paragraphs.append(text)

    images: list[dict] = []
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        src = img.get("src", "")
        if src:
            images.append({"src": src, "alt": alt})

    return {
        "title": title,
        "meta_description": meta_desc,
        "og_title": og_title,
        "headings": headings,
        "paragraphs": paragraphs[:30],  # cap per-page
        "images": images[:20],
    }


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_spec(crawl_dir: Path) -> str:
    crawl_index = load_json(crawl_dir / "crawl_index.json")
    tokens = load_json(crawl_dir / "design_tokens.json", default=EMPTY_TOKENS)
    components = load_json(crawl_dir / "components.json", default=EMPTY_COMPONENTS)

    base_domain = crawl_index["base_domain"]
    pages = crawl_index["pages"]
    catalog = components["catalog"]

    out: list[str] = []

    # ---- Header ---------------------------------------------------------
    out.append(f"# Website Specification — {base_domain}")
    out.append("")
    out.append(f"_Reverse-engineered from `{crawl_index['start_url']}` "
               f"({crawl_index['pages_crawled']} pages, "
               f"{crawl_index['css_files_downloaded']} CSS files)._")
    out.append("")
    out.append("> **Purpose of this document.** This spec is a redesign brief. "
               "It captures the existing site's information architecture, content, "
               "and observed design tokens so that a new version can be built with "
               "improved visual design while preserving structure and copy. "
               "Treat the design tokens as _evidence of the current state_, not as "
               "a prescription — the redesigner is expected to define a cleaner system.")
    out.append("")

    # ---- Redesign brief placeholder -------------------------------------
    out.append("## Redesign brief")
    out.append("")
    out.append("> _Claude should fill in this section after generation — see SKILL.md Step 5._")
    out.append("> _Bullet what to preserve (IA, key copy, brand intent) vs. what is fair "
               "game to improve (visual hierarchy, typography, spacing, component styling)._")
    out.append("")

    # ---- Sitemap --------------------------------------------------------
    out.append("## Sitemap")
    out.append("")
    ok_pages = [p for p in pages if 200 <= p.get("status", 0) < 300]
    error_pages = [p for p in pages if not (200 <= p.get("status", 0) < 300)]

    sections: dict[str, list[dict]] = defaultdict(list)
    for page in ok_pages:
        sections[section_for_url(page["url"], base_domain)].append(page)

    for section in sorted(sections.keys()):
        out.append(f"### {section}")
        out.append("")
        for page in sections[section]:
            title = page["title"] or "(no title)"
            out.append(f"- **{title}** — `{page['url']}`")
        out.append("")

    if error_pages:
        out.append("### Broken or unavailable")
        out.append("")
        out.append("_These URLs were referenced internally but did not return a successful response. "
                   "Worth deciding during redesign whether to fix, redirect, or remove the link sources._")
        out.append("")
        for page in error_pages:
            out.append(f"- `{page['url']}` — status {page.get('status', '?')}")
        out.append("")

    # ---- Design system --------------------------------------------------
    out.append("## Design system (observed)")
    out.append("")
    out.append("These tokens were extracted from the site's CSS. Frequencies indicate "
               "how often each value appears. Use them to identify the intended palette "
               "and scale, then rationalize into a clean system in the redesign.")
    out.append("")

    # Colors
    out.append("### Colors")
    out.append("")
    top_colors = tokens["colors"][:30]
    if top_colors:
        rows = [[c["value"], c["count"]] for c in top_colors]
        out.append(md_table(["Color", "Uses"], rows))
        if len(tokens["colors"]) > 30:
            out.append("")
            out.append(f"_+{len(tokens['colors']) - 30} additional colors observed._")
    else:
        out.append("_No colors detected._")
    out.append("")

    # Typography
    out.append("### Typography")
    out.append("")
    out.append("**Font families**")
    out.append("")
    if tokens["font_families"]:
        rows = [[f["value"], f["count"]] for f in tokens["font_families"][:20]]
        out.append(md_table(["Family", "Uses"], rows))
    else:
        out.append("_None detected._")
    out.append("")
    out.append("**Font sizes** (sorted)")
    out.append("")
    if tokens["font_sizes"]:
        rows = [[f["value"], f["count"]] for f in tokens["font_sizes"]]
        out.append(md_table(["Size", "Uses"], rows))
    else:
        out.append("_None detected._")
    out.append("")

    # Spacing
    out.append("### Spacing scale (observed)")
    out.append("")
    if tokens["spacing"]:
        rows = [[s["value"], s["count"]] for s in tokens["spacing"][:40]]
        out.append(md_table(["Value", "Uses"], rows))
        if len(tokens["spacing"]) > 40:
            out.append("")
            out.append(f"_+{len(tokens['spacing']) - 40} additional spacing values._")
    else:
        out.append("_None detected._")
    out.append("")

    # Border radius
    out.append("### Border radius")
    out.append("")
    if tokens["border_radius"]:
        rows = [[r["value"], r["count"]] for r in tokens["border_radius"]]
        out.append(md_table(["Radius", "Uses"], rows))
    else:
        out.append("_None detected._")
    out.append("")

    # Breakpoints
    out.append("### Breakpoints")
    out.append("")
    if tokens["breakpoints"]:
        rows = [[b["value"], b["count"]] for b in tokens["breakpoints"]]
        out.append(md_table(["Breakpoint", "Media queries"], rows))
    else:
        out.append("_None detected._")
    out.append("")

    # ---- Component catalog ----------------------------------------------
    out.append("## Component catalog")
    out.append("")
    out.append("Repeated UI patterns observed across the site. Skeletons show structural "
               "scaffolding only (tags + classes); copy is sampled separately.")
    out.append("")

    for key, label in [("header", "Header"), ("nav", "Navigation"),
                       ("footer", "Footer"), ("hero", "Hero")]:
        c = catalog.get(key)
        if not c or not c.get("samples"):
            continue
        out.append(f"### {label}")
        out.append("")
        out.append(f"_Appears on {len(c['pages'])} page(s)._")
        out.append("")
        for sample in c["samples"][:2]:
            out.append(f"**Page:** `{sample['slug']}`")
            out.append("")
            if sample.get("headline"):
                out.append(f"- Headline: {sample['headline']}")
            if sample.get("text_sample"):
                out.append(f"- Copy sample: {sample['text_sample']}")
            if sample.get("links"):
                links_summary = ", ".join(l["text"] for l in sample["links"][:10] if l["text"])
                if links_summary:
                    out.append(f"- Links: {links_summary}")
            if sample.get("skeleton"):
                out.append("")
                out.append("```html")
                out.append(sample["skeleton"])
                out.append("```")
            out.append("")

    # Cards
    if catalog.get("cards"):
        out.append("### Card patterns")
        out.append("")
        for i, card in enumerate(catalog["cards"][:10], 1):
            out.append(f"**Card pattern {i}** — {card['count']} items, "
                       f"appears on {len(card['pages'])} page(s)")
            out.append("")
            out.append(f"- Container class: `{card['container_class'] or '(none)'}`")
            out.append(f"- Child class: `{card['child_class']}`")
            if card.get("sample_text"):
                out.append(f"- Sample text: {card['sample_text']}")
            out.append("")
            out.append("```html")
            out.append(card["skeleton"])
            out.append("```")
            out.append("")
        if len(catalog["cards"]) > 10:
            out.append(f"_+{len(catalog['cards']) - 10} additional card patterns._")
            out.append("")

    # Forms
    if catalog.get("forms"):
        out.append("### Forms")
        out.append("")
        for i, form in enumerate(catalog["forms"], 1):
            out.append(f"**Form {i}** — appears on {len(form['pages'])} page(s)")
            out.append("")
            out.append(f"- Method: `{form['method'].upper()}`")
            if form["action"]:
                out.append(f"- Action: `{form['action']}`")
            if form["submit_label"]:
                out.append(f"- Submit: \"{form['submit_label']}\"")
            if form["fields"]:
                out.append("")
                rows = [
                    [f["tag"], f["type"] or "—", f["name"] or "—",
                     f["placeholder"] or "—", "yes" if f["required"] else "no"]
                    for f in form["fields"]
                ]
                out.append(md_table(["Tag", "Type", "Name", "Placeholder", "Required"], rows))
            out.append("")

    # CTAs
    if catalog.get("ctas"):
        out.append("### Calls to action")
        out.append("")
        rows = [[c["text"], c["count"]] for c in catalog["ctas"][:20]]
        out.append(md_table(["CTA text", "Occurrences"], rows))
        out.append("")

    # ---- Page-by-page content -------------------------------------------
    out.append("## Page content")
    out.append("")
    out.append("Per-page extracted copy for the redesigner. Headings preserve the "
               "original IA; paragraphs are the substantive body copy.")
    out.append("")

    pages_dir = crawl_dir / "pages"
    for page in ok_pages:
        html_file = pages_dir / f"{page['slug']}.html"
        if not html_file.exists():
            continue
        content = extract_page_content(
            html_file.read_text(encoding="utf-8", errors="replace")
        )
        out.append(f"### {page['title'] or page['url']}")
        out.append("")
        out.append(f"- **URL:** `{page['url']}`")
        if content["meta_description"]:
            out.append(f"- **Meta description:** {content['meta_description']}")
        if content["og_title"] and content["og_title"] != content["title"]:
            out.append(f"- **OG title:** {content['og_title']}")
        out.append("")

        if content["headings"]:
            out.append("**Heading outline**")
            out.append("")
            for h in content["headings"]:
                out.append(f"{'  ' * (h['level'] - 1)}- H{h['level']}: {h['text']}")
            out.append("")

        if content["paragraphs"]:
            out.append("**Body copy**")
            out.append("")
            for para in content["paragraphs"]:
                out.append(f"> {para}")
                out.append("")

        if content["images"]:
            out.append("**Images**")
            out.append("")
            rows = [[img["src"], img["alt"] or "—"] for img in content["images"]]
            out.append(md_table(["Source", "Alt text"], rows))
            out.append("")

    # ---- Footer ---------------------------------------------------------
    out.append("---")
    out.append("")
    out.append("_Generated by website-spec-extractor. Raw artifacts available alongside "
               "this spec: `crawl_index.json`, `design_tokens.json`, `components.json`._")
    out.append("")

    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="Build the final spec.md from crawl artifacts.")
    p.add_argument("--crawl-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path,
                   help="Output path for spec.md")
    args = p.parse_args()

    spec = render_spec(args.crawl_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(spec, encoding="utf-8")
    print(f"Wrote {args.output} ({len(spec):,} chars)")


if __name__ == "__main__":
    main()
