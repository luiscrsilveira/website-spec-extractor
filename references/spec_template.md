# Spec template reference

This document describes the structure of `spec.md` produced by `build_spec.py`.
Read this if you need to customize the output format or add new sections.

## Section order

1. **Title + provenance** — domain, source URL, page/CSS counts
2. **Purpose statement** — frames the spec as a redesign brief, not a clone target
3. **Redesign brief** — _human/Claude-authored_, filled in after script generation
4. **Sitemap** — pages grouped by first path segment
5. **Design system (observed)**
   - Colors (top 30 by frequency)
   - Typography (families + sizes)
   - Spacing scale
   - Border radius
   - Breakpoints
6. **Component catalog**
   - Header, Navigation, Footer, Hero (one block each, with skeleton + copy)
   - Card patterns (up to 10)
   - Forms (all, with field tables)
   - CTAs (top 20 by frequency)
7. **Page content** — per-page heading outline, body copy, images
8. **Footer** — pointer to raw JSON artifacts

## Why this order

The reader is a redesigner (human or AI) who needs:
1. To understand _what site this is_ (title, purpose)
2. To know _the rules of the redesign_ (brief)
3. To map _the structure_ (sitemap)
4. To see _the existing visual system_ as evidence (design system)
5. To know _what UI pieces to rebuild_ (components)
6. To preserve _the actual content_ (page-by-page)

The brief comes second so it's read before any tokens — preventing the
redesigner from anchoring on the existing colors as if they were the target.

## Customizing the output

To add a section, edit `build_spec.py::render_spec`. The function builds a list
of strings and joins them at the end, so you can insert new blocks anywhere by
appending to `out`.

Common customizations:
- **Reduce verbosity for large sites:** lower the `[:30]` slice on color/spacing
  tables, and the `paragraphs[:30]` cap per page.
- **Add a competitive snapshot:** append an "External references" section after
  the brief for the redesigner to compare against.
- **Strip body copy:** if the goal is purely structural, set the paragraph cap
  to 0 and rely on headings only.

## What the spec is NOT

- Not a pixel-perfect rebuild guide. There's no layout grid, no positioning data.
- Not a JS behavior spec. The crawl is requests-only; client-side interactions
  are invisible to it. If the site is heavily JS-rendered, note this in the brief.
- Not a brand guide. Brand intent (voice, mission, audience) must be inferred
  from copy by the human or by Claude during the brief-authoring step.
