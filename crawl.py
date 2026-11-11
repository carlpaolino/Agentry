"""Stage 1 - crawl: map the site, pick up to 10 useful pages, scrape them to markdown.

run(url, cdir, recrawl=False):
  - Manifest is cdir/source/sources.json. If it is missing and pages.json exists, convert pages.json
    (kind "website", method "plain", chars from the body, fetched_at from the file mtime).
    pages.json is left in place and not read again once sources.json exists.
  - A page fetched under 14 days ago is reused. When every website page is still fresh and recrawl
    is false, print the cached pages and return without calling Firecrawl.
  - Otherwise map and pick as before (at most 10). Fresh picked pages are reused; the rest are scraped.
    recrawl=True fetches every picked page again.
  - Each scrape: formats ["markdown", "links"], only_main_content=False, wait_for=1500.
    FAQ, pricing, services, and service-area URLs open closed accordions and <details> first.
    A thin or loader page is scraped again (wait, scroll, scrape).
  - Save cdir/source/pages/<slug>.md (first line = URL) and source/discovered_links.json.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import anthropic
from firecrawl import Firecrawl
from firecrawl.v2.types import ExecuteJavascriptAction, ScrapeAction, ScrollAction, WaitAction
from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape

MAX_CANDIDATES = 200
MAX_PAGES = 10
CACHE_DAYS = 14
THIN_CHARS = 600
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_WAIT = 30
console = Console(highlight=False, soft_wrap=True)

PICK_SYSTEM = """You pick pages from a home-service company's website (HVAC, plumbing, cleaning).
The pages will be used to brief a phone receptionist about the business.

Pick up to 10 URLs, most useful first. Always include the home page. Prefer:
home, services and service sub-pages, about, contact, service areas, pricing, FAQ, reviews,
financing, emergency service.
Skip blog posts, news, careers, privacy, terms, login, cart, and near-duplicate pages.
Only return URLs exactly as they appear in the list."""

OPEN_HIDDEN_JS = """(() => {
  const closed = document.querySelectorAll('[aria-expanded="false"]');
  closed.forEach((el) => el.click());
  document.querySelectorAll('details:not([open])').forEach((el) => { el.open = true; });
  return closed.length;
})()"""

SCROLL_TO_BOTTOM_JS = """(() => {
  const height = Math.max(
    document.body ? document.body.scrollHeight : 0,
    document.documentElement ? document.documentElement.scrollHeight : 0
  );
  window.scrollTo(0, height);
  return height;
})()"""

LOADER_RE = re.compile(
    r"enable\s+javascript|enable\s+js|just a moment|checking your browser", re.I)
BARE_LOADING_RE = re.compile(r"^(loading|please wait)[.!\s]*$", re.I)
COOKIE_RE = re.compile(r"\bcookies?\b|\bconsent\b|accept all", re.I)


class PagePick(BaseModel):
    urls: list[str]


def fail(message: str) -> None:
    console.print(f"[red]crawl failed:[/red] {escape(message)}")
    sys.exit(1)


def normalize(u: str) -> str:
    return u.split("#")[0].rstrip("/")


def path_depth(u: str) -> tuple:
    path = urlparse(u).path.strip("/")
    return (path.count("/") + (1 if path else 0), len(u))


def file_slug(u: str) -> str:
    path = urlparse(u).path.strip("/").lower()
    path = re.sub(r"\.(html?|php|aspx?)$", "", path)
    return re.sub(r"[^a-z0-9]+", "-", path).strip("-")[:80] or "home"


def opens_hidden(url: str) -> bool:
    """FAQ, pricing, services, and service-area pages. Empire's FAQ slug has no 'faq' in it."""
    path = urlparse(url).path.lower()
    return any(part in path for part in ("faq", "frequently-asked", "pric", "service"))


def real_text(markdown: str) -> str:
    """Visible words, with image and link markup and raw URLs removed."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r" \1 ", markdown)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r" \1 ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[#>*_`\[\]()|-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_thin(markdown: str) -> bool:
    text = real_text(markdown)
    if len(text) < THIN_CHARS:
        return True
    if LOADER_RE.search(text) and len(text) < THIN_CHARS * 2:
        return True
    if BARE_LOADING_RE.match(text):
        return True
    # A cookie banner with almost nothing else is a shell, not a page.
    return bool(COOKIE_RE.search(text) and len(text) < 800)


def hidden_actions(url: str) -> list:
    if not opens_hidden(url):
        return []
    return [ExecuteJavascriptAction(script=OPEN_HIDDEN_JS), WaitAction(milliseconds=800)]


def thin_actions(url: str) -> list:
    actions = [
        WaitAction(milliseconds=2000),
        ExecuteJavascriptAction(script=SCROLL_TO_BOTTOM_JS),
        ScrollAction(direction="down"),
        WaitAction(milliseconds=1000),
    ]
    actions.extend(hidden_actions(url))
    actions.append(ScrapeAction())
    return actions


def parse_fetched_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def is_fresh(entry: dict, cdir: Path, now: datetime) -> bool:
    when = parse_fetched_at(entry.get("fetched_at") or "")
    path = cdir / (entry.get("file") or "")
    return bool(when and path.is_file() and (now - when) < timedelta(days=CACHE_DAYS))


def body_chars(path: Path) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text().splitlines()
    return len("\n".join(lines[1:]).strip())


def load_sources(cdir: Path) -> list[dict]:
    source = cdir / "source"
    sources_path = source / "sources.json"
    if sources_path.exists():
        return json.loads(sources_path.read_text())
    pages_json = source / "pages.json"
    if not pages_json.exists():
        return []
    converted = []
    for item in json.loads(pages_json.read_text()):
        path = cdir / item["file"]
        when = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if path.is_file() else None
        converted.append({
            "url": item["url"],
            "file": item["file"],
            "kind": "website",
            "method": "plain",
            "chars": body_chars(path),
            "fetched_at": when.isoformat() if when else "",
        })
    source.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(json.dumps(converted, indent=2))
    console.print(f"Migrated {len(converted)} pages from {pages_json.name} -> {sources_path.name}")
    return converted


def get_candidates(fc: Firecrawl, url: str) -> list[dict]:
    links = fc.map(url).links or []
    seen, out = set(), []
    for link in [{"url": url}] + [
        {"url": l.url, "title": l.title or ""} if hasattr(l, "url") else {"url": str(l)}
        for l in links
    ]:
        key = normalize(link["url"])
        if key and key not in seen:
            seen.add(key)
            out.append(link)
    home, rest = out[0], sorted(out[1:], key=lambda l: path_depth(l["url"]))
    return [home] + rest[: MAX_CANDIDATES - 1]


def pick_pages(candidates: list[dict], home: str) -> list[str]:
    listing = "\n".join(
        f"{c['url']}" + (f"  ({c['title']})" if c.get("title") else "") for c in candidates
    )
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.parse(
        model="claude-haiku-5-5",
        max_tokens=2000,
        system=PICK_SYSTEM,
        messages=[{"role": "user", "content": f"Home page: {home}\n\nCandidate URLs:\n{listing}"}],
        output_format=PagePick,
    )
    allowed = {normalize(c["url"]): c["url"] for c in candidates}
    picked = []
    for u in [home] + resp.parsed_output.urls:
        real = allowed.get(normalize(u))
        if real and real not in picked:
            picked.append(real)
    return picked[:MAX_PAGES]


def link_urls(raw) -> list[str]:
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("url"):
            out.append(item["url"])
        else:
            url = getattr(item, "url", None)
            if url:
                out.append(url)
    return out


def call_scrape(fc: Firecrawl, page: str, actions: list) -> tuple[str, list[str]]:
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            doc = fc.scrape(
                page, formats=["markdown", "links"], only_main_content=False,
                wait_for=1500, actions=actions or None,
            )
            markdown = (getattr(doc, "markdown", None) or "").strip()
            if not markdown:
                raise RuntimeError("no markdown returned")
            return markdown, link_urls(getattr(doc, "links", None))
        except Exception as e:
            if "rate limit" not in str(e).lower() or attempt == RATE_LIMIT_RETRIES:
                raise
            console.print(f"  rate limited; waiting {RATE_LIMIT_WAIT}s before retrying {page}")
            time.sleep(RATE_LIMIT_WAIT)


def fetch_page(fc: Firecrawl, page: str) -> tuple[str, list[str]]:
    markdown, links = call_scrape(fc, page, hidden_actions(page))
    if not is_thin(markdown):
        return markdown, links
    console.print(f"  thin page ({len(real_text(markdown)):,} chars of text); retrying {page}")
    try:
        return call_scrape(fc, page, thin_actions(page))
    except Exception as e:
        console.print(f"  [yellow]thin retry failed[/yellow] {page}: {escape(str(e).splitlines()[0][:150])}")
        return markdown, links


def page_path(page: str, entry: dict | None, used: set, pages_dir: Path) -> Path:
    if entry and entry.get("file"):
        name = Path(entry["file"]).stem
    else:
        name = file_slug(page)
        while name in used:
            name += "-2"
    used.add(name)
    return pages_dir / f"{name}.md"


def run(url: str, cdir: Path, recrawl: bool = False) -> None:
    source = cdir / "source"
    pages_dir = source / "pages"
    sources = load_sources(cdir)
    now = datetime.now(timezone.utc)
    website = [entry for entry in sources if entry.get("kind", "website") == "website"]
    if not recrawl and website and all(is_fresh(entry, cdir, now) for entry in website):
        for entry in website:
            console.print(
                f"  cached {Path(entry['file']).name} ({entry.get('chars', 0):,} chars, "
                f"fetched {entry.get('fetched_at', '')})")
        console.print(f"Cache is fresh ({len(website)} pages, under {CACHE_DAYS} days); nothing fetched")
        return

    for name in ("FIRECRAWL_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.getenv(name):
            fail(f"{name} is not set in .env")

    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    try:
        candidates = get_candidates(fc, url)
    except Exception as e:
        fail(f"map {url}: {type(e).__name__}: {e}")
    console.print(f"Mapped {url}: {len(candidates)} candidate URLs")

    try:
        picked = pick_pages(candidates, url)
    except Exception as e:
        fail(f"page picking: {type(e).__name__}: {e}")
    console.print(f"Picked {len(picked)} pages")

    pages_dir.mkdir(parents=True, exist_ok=True)
    by_url = {normalize(entry["url"]): entry for entry in website if entry.get("url")}
    links_path = source / "discovered_links.json"
    discovered = json.loads(links_path.read_text()) if links_path.exists() else {}
    saved, used = [], set()
    for page in picked:
        entry = by_url.get(normalize(page))
        path = page_path(page, entry, used, pages_dir)
        rel = str(path.relative_to(cdir))
        if entry and not recrawl and is_fresh(entry, cdir, now):
            saved.append(dict(entry, file=rel))
            console.print(f"  cached {path.name} ({entry.get('chars', 0):,} chars)  {page}")
            continue
        try:
            markdown, links = fetch_page(fc, page)
        except Exception as e:
            console.print(f"  [yellow]skip[/yellow] {page}: {escape(str(e).splitlines()[0][:150])}")
            if entry and path.is_file():
                saved.append(dict(entry, file=rel))
            continue
        path.write_text(f"{page}\n\n{markdown}\n")
        discovered[page] = links
        saved.append({
            "url": page,
            "file": rel,
            "kind": "website",
            "method": "rendered",
            "chars": len(markdown),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
        console.print(f"  saved {path.name} ({len(markdown):,} chars)  {page}")

    if not saved:
        fail("no pages could be scraped")
    others = [entry for entry in sources if entry.get("kind") not in (None, "website")]
    source.mkdir(parents=True, exist_ok=True)
    (source / "sources.json").write_text(json.dumps(saved + others, indent=2))
    links_path.write_text(json.dumps(discovered, indent=2))
    console.print(f"Crawled {len(saved)} pages -> {source / 'sources.json'}")
