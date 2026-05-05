#!/usr/bin/env python3
"""
extract_components.py — Catalog repeated UI patterns from crawled HTML.

Identifies common component types (header, nav, footer, hero, cards, forms,
CTAs) using a mix of semantic-tag detection and class-name heuristics.

For each component, records:
  - which pages it appears on
  - an HTML skeleton (tags + classes, no full body text)
  - representative copy variants

Writes components.json to <crawl_dir>/.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# Class-name hints (substring match, case-insensitive)
CTA_HINTS = ("btn", "button", "cta", "call-to-action")
HERO_HINTS = ("hero", "banner", "jumbotron", "masthead")
CARD_HINTS = ("card", "tile", "feature", "service-item", "post", "article-item")
NAV_HINTS = ("nav", "menu", "navbar")
HEADER_HINTS = ("header", "site-header", "topbar")
FOOTER_HINTS = ("footer", "site-footer")


def class_str(tag: Tag) -> str:
    classes = tag.get("class") or []
    return " ".join(classes).lower() if classes else ""


def matches_hint(tag: Tag, hints: tuple[str, ...]) -> bool:
    cls = class_str(tag)
    if any(h in cls for h in hints):
        return True
    tid = (tag.get("id") or "").lower()
    if any(h in tid for h in hints):
        return True
    return False


def short_text(tag: Tag, limit: int = 120) -> str:
    text = tag.get_text(" ", strip=True)
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def skeleton(tag: Tag, max_depth: int = 3, depth: int = 0) -> str:
    """Compact HTML skeleton: tag + classes only, truncated by depth."""
    if depth > max_depth:
        return f"<{tag.name}>…</{tag.name}>" if tag.name else "…"
    cls = class_str(tag)
    cls_attr = f' class="{cls}"' if cls else ""
    children = [c for c in tag.children if isinstance(c, Tag)]
    if not children:
        # Leaf — show truncated text if any
        text = tag.get_text(strip=True)
        text_part = f"{text[:40]}{'…' if len(text) > 40 else ''}" if text else ""
        return f"<{tag.name}{cls_attr}>{text_part}</{tag.name}>"
    inner = "".join(skeleton(c, max_depth, depth + 1) for c in children[:8])
    if len(children) > 8:
        inner += f"<!-- +{len(children) - 8} more -->"
    return f"<{tag.name}{cls_attr}>{inner}</{tag.name}>"


def find_first(soup: BeautifulSoup, names: list[str], hints: tuple[str, ...]) -> Tag | None:
    """Find by semantic tag first, then fall back to class hint match."""
    for name in names:
        tag = soup.find(name)
        if tag:
            return tag
    for tag in soup.find_all(["div", "section"]):
        if matches_hint(tag, hints):
            return tag
    return None


def detect_hero(soup: BeautifulSoup) -> Tag | None:
    # 1) Class-hinted hero
    for tag in soup.find_all(["section", "div", "header"]):
        if matches_hint(tag, HERO_HINTS):
            return tag
    # 2) First <section> after the header containing an h1
    main = soup.find("main") or soup.body or soup
    for sec in main.find_all("section", limit=5):
        if sec.find("h1"):
            return sec
    # 3) First h1 ancestor
    h1 = (soup.find("main") or soup).find("h1") if (soup.find("main") or soup) else soup.find("h1")
    if h1:
        return h1.find_parent(["section", "div", "header"]) or h1
    return None


def detect_cards(soup: BeautifulSoup) -> list[dict]:
    """A 'card group' is a container with 3+ similar children."""
    candidates: list[dict] = []
    for container in soup.find_all(["div", "section", "ul", "ol"]):
        children = [c for c in container.children if isinstance(c, Tag)]
        if len(children) < 3:
            continue
        # Children must share the same tag name
        tag_names = {c.name for c in children}
        if len(tag_names) > 1:
            continue
        # Children must share at least one class
        class_sets = [set((c.get("class") or [])) for c in children]
        if not class_sets[0]:
            continue
        common = set.intersection(*class_sets) if class_sets else set()
        if not common:
            continue
        # Cards usually have meaningful inner structure (image, heading, or text)
        first_child = children[0]
        has_structure = bool(
            first_child.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            or first_child.find("img")
            or len(first_child.find_all(True)) >= 2
        )
        if not has_structure:
            continue
        # Class hint OR clearly card-shaped
        is_hinted = any(h in " ".join(common).lower() for h in CARD_HINTS)
        if not is_hinted and len(children) < 3:
            continue
        candidates.append({
            "container_class": class_str(container),
            "child_class": " ".join(sorted(common)),
            "count": len(children),
            "skeleton": skeleton(first_child, max_depth=3),
            "sample_text": short_text(first_child, 200),
        })
    # Deduplicate by (child_class, count)
    seen = set()
    unique: list[dict] = []
    for c in candidates:
        key = (c["child_class"], c["count"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def detect_forms(soup: BeautifulSoup) -> list[dict]:
    forms: list[dict] = []
    for form in soup.find_all("form"):
        fields = []
        for inp in form.find_all(["input", "textarea", "select"]):
            fields.append({
                "tag": inp.name,
                "type": inp.get("type", ""),
                "name": inp.get("name", ""),
                "placeholder": inp.get("placeholder", ""),
                "required": inp.has_attr("required"),
            })
        submit = form.find(["button", "input"], attrs={"type": "submit"}) or form.find("button")
        forms.append({
            "action": form.get("action", ""),
            "method": form.get("method", "get").lower(),
            "fields": fields,
            "submit_label": short_text(submit, 60) if submit else "",
        })
    return forms


def detect_ctas(soup: BeautifulSoup) -> list[dict]:
    ctas: list[dict] = []
    for tag in soup.find_all(["a", "button"]):
        cls = class_str(tag)
        is_button_tag = tag.name == "button"
        is_class_cta = any(h in cls for h in CTA_HINTS)
        if not (is_button_tag or is_class_cta):
            continue
        text = short_text(tag, 80)
        if not text:
            continue
        ctas.append({
            "tag": tag.name,
            "text": text,
            "class": cls,
            "href": tag.get("href", "") if tag.name == "a" else "",
        })
    return ctas


def analyze_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    header = find_first(soup, ["header"], HEADER_HINTS)
    nav = find_first(soup, ["nav"], NAV_HINTS)
    footer = find_first(soup, ["footer"], FOOTER_HINTS)
    hero = detect_hero(soup)

    return {
        "header": {
            "skeleton": skeleton(header, max_depth=3) if header else None,
            "text_sample": short_text(header, 300) if header else "",
        } if header else None,
        "nav": {
            "skeleton": skeleton(nav, max_depth=3) if nav else None,
            "links": [
                {"text": short_text(a, 40), "href": a.get("href", "")}
                for a in (nav.find_all("a") if nav else [])
            ][:30],
        } if nav else None,
        "footer": {
            "skeleton": skeleton(footer, max_depth=3) if footer else None,
            "text_sample": short_text(footer, 400) if footer else "",
        } if footer else None,
        "hero": {
            "skeleton": skeleton(hero, max_depth=3) if hero else None,
            "headline": short_text(hero.find(["h1", "h2"]), 200) if hero and hero.find(["h1", "h2"]) else "",
            "text_sample": short_text(hero, 400) if hero else "",
        } if hero else None,
        "cards": detect_cards(soup),
        "forms": detect_forms(soup),
        "ctas": detect_ctas(soup),
    }


def aggregate(per_page: dict[str, dict]) -> dict:
    """Roll per-page detections up into a site-wide component catalog."""
    catalog: dict = {
        "header": {"pages": [], "samples": []},
        "nav": {"pages": [], "samples": []},
        "footer": {"pages": [], "samples": []},
        "hero": {"pages": [], "samples": []},
        "cards": [],
        "forms": [],
        "ctas": defaultdict(lambda: {"count": 0, "examples": []}),
    }

    for slug, page in per_page.items():
        for key in ("header", "nav", "footer", "hero"):
            if page.get(key):
                catalog[key]["pages"].append(slug)
                # Keep up to 3 distinct skeletons
                skel = page[key].get("skeleton")
                existing_skels = [s.get("skeleton") for s in catalog[key]["samples"]]
                if skel and skel not in existing_skels and len(catalog[key]["samples"]) < 3:
                    catalog[key]["samples"].append({"slug": slug, **page[key]})

        for card in page.get("cards", []):
            existing = next(
                (c for c in catalog["cards"]
                 if c["child_class"] == card["child_class"]),
                None,
            )
            if existing:
                if slug not in existing["pages"]:
                    existing["pages"].append(slug)
            else:
                catalog["cards"].append({**card, "pages": [slug]})

        for form in page.get("forms", []):
            field_sig = tuple((f["tag"], f["type"], f["name"]) for f in form["fields"])
            existing = next(
                (f for f in catalog["forms"]
                 if tuple((x["tag"], x["type"], x["name"]) for x in f["fields"]) == field_sig),
                None,
            )
            if existing:
                if slug not in existing["pages"]:
                    existing["pages"].append(slug)
            else:
                catalog["forms"].append({**form, "pages": [slug]})

        for cta in page.get("ctas", []):
            text_norm = cta["text"].lower().strip()
            entry = catalog["ctas"][text_norm]
            entry["count"] += 1
            if len(entry["examples"]) < 3:
                entry["examples"].append({"slug": slug, **cta})

    # Convert CTAs dict to sorted list
    catalog["ctas"] = sorted(
        [{"text": k, **v} for k, v in catalog["ctas"].items()],
        key=lambda x: -x["count"],
    )[:30]

    return catalog


def main():
    p = argparse.ArgumentParser(description="Catalog UI components from crawled HTML.")
    p.add_argument("--crawl-dir", required=True, type=Path)
    args = p.parse_args()

    pages_dir = args.crawl_dir / "pages"
    if not pages_dir.exists():
        print(f"No pages directory at {pages_dir}", file=__import__("sys").stderr)
        return

    per_page: dict[str, dict] = {}
    for html_file in sorted(pages_dir.glob("*.html")):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        per_page[html_file.stem] = analyze_page(html)

    catalog = aggregate(per_page)

    out = args.crawl_dir / "components.json"
    out.write_text(json.dumps({"per_page": per_page, "catalog": catalog},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"  card patterns: {len(catalog['cards'])}")
    print(f"  forms:         {len(catalog['forms'])}")
    print(f"  unique CTAs:   {len(catalog['ctas'])}")


if __name__ == "__main__":
    main()
