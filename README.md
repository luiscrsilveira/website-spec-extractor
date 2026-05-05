# Website Spec Extractor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Reverse-engineer a live website into a redesign-ready `spec.md` — sitemap, design system, component catalog, and page content — using only Python requests (no browser automation).

## What it produces

A single `spec.md` containing:

1. **Site overview** — name, URL, inferred purpose
2. **Sitemap** — every crawled URL grouped by section
3. **Design system** — color palette, typography scale, spacing tokens, border radii, breakpoints
4. **Component catalog** — header, nav, hero, cards, footer, forms, CTAs with HTML skeletons
5. **Page-by-page content** — headings, copy, images, CTAs per page
6. **Redesign brief** — what to preserve vs. what's fair game to improve

The spec is a brief for a redesigner (or another AI agent), not a description of the original.

## Pipeline

```
URL → crawl.py → pages/*.html + assets/*.css + crawl_index.json
               → extract_design.py  → design_tokens.json
               → extract_components.py → components.json
               → build_spec.py → spec.md
```

## Usage

### 1. Crawl

```bash
python scripts/crawl.py https://example.com \
  --output-dir /tmp/work/example.com \
  --max-pages 50 \
  --delay 0.5
```

Flags: `--max-pages N` · `--max-depth N` · `--no-robots` · `--include-subdomains`

### 2. Extract design tokens

```bash
python scripts/extract_design.py --crawl-dir /tmp/work/example.com
```

Outputs `design_tokens.json`: colors, fonts, spacing, radii, breakpoints.

### 3. Catalog components

```bash
python scripts/extract_components.py --crawl-dir /tmp/work/example.com
```

Outputs `components.json`: repeated structural patterns across pages.

### 4. Build spec

```bash
python scripts/build_spec.py \
  --crawl-dir /tmp/work/example.com \
  --output /tmp/outputs/example.com/spec.md
```

## Requirements

```bash
pip install requests beautifulsoup4 cssutils
```

## Constraints

- **No browser automation** — requests-only by design. JS-heavy sites will have limited extraction; limitations are noted in the spec.
- **Polite crawling** — 0.5s default delay; respects `robots.txt` unless `--no-robots` passed.
- **No fabricated tokens** — observed values only; no invented design scales.

## Claude Code skill

This repo ships as a [Claude Code](https://claude.ai/code) skill (`SKILL.md`). When installed, Claude automatically uses this pipeline when asked to "reverse engineer a site", "extract the design from X", or "clone the spec" for a URL.

## License

[MIT](LICENSE)
