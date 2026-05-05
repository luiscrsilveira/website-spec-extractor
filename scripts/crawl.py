#!/usr/bin/env python3
"""
crawl.py — Discover and download pages from a website using requests.

Walks every internal link on the same registrable domain (BFS), saves raw HTML
per page, downloads referenced stylesheets, and emits crawl_index.json.

No browser automation. No JS execution. Pure requests + BeautifulSoup.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; WebsiteSpecExtractor/1.0; "
    "+reverse-engineering for redesign spec) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}


def registrable_domain(netloc: str) -> str:
    """Strip leading 'www.' for same-domain comparison. Doesn't handle full PSL."""
    return netloc.lower().lstrip("www.") if netloc.lower().startswith("www.") else netloc.lower()


def normalize_url(url: str) -> str:
    """Drop fragments and trailing slashes from path (except root). Collapse /index.html to /."""
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path
    # Treat /index.html as /
    if path.lower().endswith("/index.html"):
        path = path[: -len("index.html")]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if path == "":
        path = "/"
    return parsed._replace(path=path, fragment="").geturl()


def slugify(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", path).strip("_")
    if parsed.query:
        slug += "_" + hashlib.md5(parsed.query.encode()).hexdigest()[:8]
    return slug or "index"


def looks_like_asset(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def load_robots(start_url: str, session: requests.Session) -> RobotFileParser | None:
    parsed = urlparse(start_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        resp = session.get(robots_url, timeout=10)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            return rp
    except requests.RequestException:
        pass
    return None


def fetch(url: str, session: requests.Session, timeout: int = 15) -> requests.Response | None:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        # `requests` defaults to ISO-8859-1 if Content-Type doesn't specify a charset,
        # which mangles UTF-8 sites. Use apparent_encoding (chardet) when needed.
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            detected = resp.apparent_encoding
            if detected:
                resp.encoding = detected
        return resp
    except requests.RequestException as e:
        print(f"  [error] {url}: {e}", file=sys.stderr)
        return None


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        links.append(normalize_url(absolute))
    return links


def extract_css_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.find_all("link", rel=True, href=True):
        rels = link.get("rel", [])
        if "stylesheet" in [r.lower() for r in rels]:
            links.append(urljoin(base_url, link["href"]))
    return links


def extract_image_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img", src=True):
        images.append(urljoin(base_url, img["src"]))
    return images


def download_css(url: str, css_dir: Path, session: requests.Session) -> str | None:
    """Download a CSS file. Returns the saved filename, or None on failure."""
    digest = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = f"{digest}.css"
    target = css_dir / filename
    if target.exists():
        return filename
    resp = fetch(url, session)
    if resp is None or resp.status_code != 200:
        return None
    target.write_text(resp.text, encoding="utf-8", errors="replace")
    # Sidecar with original URL for traceability
    (css_dir / f"{digest}.url").write_text(url, encoding="utf-8")
    return filename


def crawl(
    start_url: str,
    output_dir: Path,
    max_pages: int,
    max_depth: int | None,
    delay: float,
    respect_robots: bool,
    include_subdomains: bool,
) -> dict:
    start_url = normalize_url(start_url)
    parsed_start = urlparse(start_url)
    if not parsed_start.scheme or not parsed_start.netloc:
        print(f"Invalid start URL: {start_url}", file=sys.stderr)
        sys.exit(1)

    base_domain = registrable_domain(parsed_start.netloc)

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    css_dir = output_dir / "assets" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    robots = load_robots(start_url, session) if respect_robots else None
    if respect_robots and robots is None:
        print("  [info] no robots.txt found or unreachable; proceeding", file=sys.stderr)

    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    seen: set[str] = {start_url}
    pages: list[dict] = []
    css_seen: dict[str, str] = {}  # url -> filename

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()

        if max_depth is not None and depth > max_depth:
            continue

        if respect_robots and robots is not None and not robots.can_fetch(USER_AGENT, url):
            print(f"  [robots] skipping {url}", file=sys.stderr)
            continue

        print(f"[{len(pages) + 1}/{max_pages}] depth={depth} {url}")
        resp = fetch(url, session)
        if delay > 0:
            time.sleep(delay)
        if resp is None:
            continue

        # Verify content type is HTML
        content_type = resp.headers.get("content-type", "").lower()
        if "html" not in content_type and resp.status_code == 200:
            print(f"  [skip] non-html content-type: {content_type}", file=sys.stderr)
            continue

        slug = slugify(url)
        # Avoid slug collisions
        original_slug = slug
        suffix = 1
        while any(p["slug"] == slug for p in pages):
            slug = f"{original_slug}_{suffix}"
            suffix += 1

        html = resp.text if resp.status_code == 200 else ""
        if html:
            (pages_dir / f"{slug}.html").write_text(html, encoding="utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser") if html else None
        title = ""
        if soup and soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Find and download CSS
        css_files: list[str] = []
        if html:
            for css_url in extract_css_links(html, url):
                if css_url in css_seen:
                    css_files.append(css_seen[css_url])
                else:
                    saved = download_css(css_url, css_dir, session)
                    if saved:
                        css_seen[css_url] = saved
                        css_files.append(saved)
                    if delay > 0:
                        time.sleep(delay / 2)

        images = extract_image_urls(html, url) if html else []
        internal_links: list[str] = []

        # Discover new links
        if html:
            for link in extract_links(html, url):
                parsed_link = urlparse(link)
                if not parsed_link.scheme.startswith("http"):
                    continue
                if looks_like_asset(link):
                    continue
                link_domain = registrable_domain(parsed_link.netloc)
                same_domain = (
                    link_domain == base_domain
                    if not include_subdomains
                    else link_domain.endswith(base_domain)
                )
                if not same_domain:
                    continue
                internal_links.append(link)
                if link not in seen:
                    seen.add(link)
                    queue.append((link, depth + 1))

        pages.append({
            "url": url,
            "title": title,
            "slug": slug,
            "depth": depth,
            "status": resp.status_code,
            "css_files": css_files,
            "images": images[:50],  # cap to keep index small
            "internal_links": list(dict.fromkeys(internal_links))[:100],
        })

    index = {
        "start_url": start_url,
        "base_domain": base_domain,
        "include_subdomains": include_subdomains,
        "pages_crawled": len(pages),
        "css_files_downloaded": len(css_seen),
        "pages": pages,
        "css_url_map": {url: name for url, name in css_seen.items()},
    }

    (output_dir / "crawl_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nCrawled {len(pages)} pages, downloaded {len(css_seen)} CSS files.")
    print(f"Output: {output_dir}")
    return index


def main():
    p = argparse.ArgumentParser(description="Crawl a website using requests.")
    p.add_argument("url", help="Start URL (must include scheme)")
    p.add_argument("--output-dir", required=True, type=Path,
                   help="Directory to write pages/, assets/css/, and crawl_index.json")
    p.add_argument("--max-pages", type=int, default=50, help="Hard cap on pages crawled")
    p.add_argument("--max-depth", type=int, default=None, help="Max link depth from start URL")
    p.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    p.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
    p.add_argument("--include-subdomains", action="store_true",
                   help="Crawl subdomains of the start domain")
    args = p.parse_args()

    crawl(
        start_url=args.url,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        respect_robots=not args.no_robots,
        include_subdomains=args.include_subdomains,
    )


if __name__ == "__main__":
    main()
