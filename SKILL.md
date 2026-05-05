---
name: website-spec-extractor
description: Reverse-engineer a live website into a complete redesign specification by crawling its pages with Python requests, parsing HTML/CSS, and producing a single spec.md that captures the sitemap, design system, UI component catalog, and page content. Use this skill whenever the user provides a website URL and wants to extract its structure, "clone the spec," "reverse engineer the site," "audit the design system," "rebuild this site with better design," or generate a specification that another agent can use to produce an improved version of the site. Trigger this even when the user says things like "analyze this site," "extract the design from X," or "I want to redesign this — start from a spec." Do NOT use browser automation (Playwright, Puppeteer, Selenium) — this skill is intentionally requests-based.
---

# Website Spec Extractor

Reverse-engineer a live website into a redesign-ready specification.

## What this skill produces

A single `spec.md` file at `/mnt/user-data/outputs/<domain>/spec.md` containing:

1. **Site overview** — name, URL, purpose inferred from content
2. **Sitemap** — every crawled URL grouped by section
3. **Design system** — color palette, typography scale, spacing tokens, observed border radii
4. **Component catalog** — repeated UI patterns (header, nav, hero, cards, footer, forms, CTAs, etc.) with structural notes
5. **Page-by-page content** — copy, headings, images, CTAs for each page

The spec is meant to be fed to another agent (or to Claude in a fresh session) to rebuild the site with improved design while preserving structure and content. Be explicit about that downstream use when writing the spec — it is a brief for a redesigner, not a description of the original.

## Workflow

Run the four scripts in order. Each writes intermediate artifacts that the next step reads. This keeps memory low and lets the user inspect intermediate outputs.

```
URL → crawl.py → pages/*.html + assets/*.css + crawl_index.json
              → extract_design.py → design_tokens.json
              → extract_components.py → components.json
              → build_spec.py → spec.md
```

### Step 1 — Confirm the URL and scope

Before running anything, confirm with the user:
- The exact starting URL (with scheme — `https://...`)
- Whether to respect robots.txt (default: yes)
- Page cap (default: 50; bigger sites need an explicit higher cap)

If the user gave you the URL with enough context already, just proceed and state the assumptions inline.

### Step 2 — Crawl

```bash
python scripts/crawl.py <url> --output-dir /home/claude/work/<domain> --max-pages 50
```

Flags:
- `--max-pages N` (default 50) — hard cap on pages crawled
- `--max-depth N` (default unlimited within same domain) — link depth from start URL
- `--no-robots` — ignore robots.txt (only if user explicitly asked)
- `--delay 0.5` — seconds between requests (be polite)

The crawler:
- Stays on the same registrable domain (subdomains optional via `--include-subdomains`)
- Skips binary assets (pdf, zip, images) but records image URLs for the spec
- Saves each page's raw HTML to `pages/<slug>.html`
- Downloads referenced CSS files to `assets/css/<hash>.css`
- Writes `crawl_index.json` with one entry per page: `{url, title, slug, depth, status, css_files, images, internal_links}`

If a page returns non-200, log it but keep going. If the start URL fails, abort with a clear message.

### Step 3 — Extract the design system

```bash
python scripts/extract_design.py --crawl-dir /home/claude/work/<domain>
```

Reads all CSS files plus inline `<style>` blocks. Produces `design_tokens.json`:
- `colors` — deduplicated hex/rgb values with usage frequency
- `font_families` — every font-family declared
- `font_sizes` — sorted set of font sizes with frequency
- `spacing` — observed margin/padding values (helps infer the spacing scale)
- `border_radius` — observed radii
- `breakpoints` — media query thresholds

### Step 4 — Catalog components

```bash
python scripts/extract_components.py --crawl-dir /home/claude/work/<domain>
```

Parses each saved HTML page and identifies repeated structural patterns. Produces `components.json` listing:
- `header` / `nav` / `footer` — inferred from `<header>`, `<nav>`, `<footer>` and common class names
- `hero` — the first large block on landing-style pages
- `cards` — repeated similar children inside grid/flex containers
- `forms` — every `<form>` with its fields
- `ctas` — prominent buttons/links (by class hints like `btn`, `cta`, `button`)

For each component, record: where it appears (which pages), an HTML skeleton (tags + classes, no full text), and the copy variants.

### Step 5 — Build the spec

```bash
python scripts/build_spec.py --crawl-dir /home/claude/work/<domain> --output /mnt/user-data/outputs/<domain>/spec.md
```

This script assembles the final markdown using the template at `references/spec_template.md`. It pulls from `crawl_index.json`, `design_tokens.json`, and `components.json`.

After the script runs, read the generated spec.md and add a short **"Redesign brief"** section at the top — 5-10 bullets describing what the next designer should preserve (information architecture, key copy, brand colors if intentional) versus what is fair game to improve (visual hierarchy, spacing, component styling, typography). This is the part that requires judgment and shouldn't be templated.

### Step 6 — Present the spec

Use the `present_files` tool with the path to `spec.md` so the user can download it. Summarize in 2-3 sentences what was extracted (page count, color count, components found) — don't repeat the spec itself in chat.

## Important constraints

- **Never use Playwright, Puppeteer, Selenium, or any browser automation.** This skill is intentionally requests-only. If a site is heavily JS-rendered and the requests crawl returns mostly empty pages, say so explicitly in the spec under a "Limitations" section rather than switching tools.
- **Be polite when crawling.** Default 0.5s delay between requests; respect robots.txt unless the user opts out.
- **Don't fabricate design tokens.** If the CSS doesn't define a clear scale, list what was observed rather than inventing one.
- **Component detection is heuristic.** When patterns are ambiguous, prefer fewer high-confidence components over many speculative ones. The spec should be useful, not exhaustive.

## Reference files

- `references/spec_template.md` — the markdown template `build_spec.py` fills in. Read this if the user asks to customize the spec format.
