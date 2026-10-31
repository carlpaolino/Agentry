"""Stage 1 - crawl: map the site, pick up to 10 useful pages, scrape them to markdown.

run(url, cdir):
  - If cdir/source/pages.json exists, print "already crawled" and return.
  - Firecrawl v2: Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"]).map(url) -> candidate URLs.
  - One Claude call (model "claude-haiku-5-5", structured output: list of URLs) picks up to 10:
    home, services (and service sub-pages), about, contact, service areas, pricing, FAQ, reviews,
    financing, emergency. Skip blog posts, careers, privacy, login.
  - .scrape(page, formats=["markdown"]) each; save cdir/source/pages/<slug-of-path>.md with the
    page URL as the first line; skip pages that fail and keep going.
  - Write cdir/source/pages.json = [{"url": ..., "file": ...}].
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import anthropic
from firecrawl import Firecrawl
from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape

MAX_CANDIDATES = 200
MAX_PAGES = 10
console = Console(highlight=False, soft_wrap=True)

PICK_SYSTEM = """You pick pages from a home-service company's website (HVAC, plumbing, cleaning).
The pages will be used to brief a phone receptionist about the business.

Pick up to 10 URLs, most useful first. Always include the home page. Prefer:
home, services and service sub-pages, about, contact, service areas, pricing, FAQ, reviews,
financing, emergency service.
Skip blog posts, news, careers, privacy, terms, login, cart, and near-duplicate pages.
Only return URLs exactly as they appear in the list."""


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


def run(url: str, cdir: Path) -> None:
    pages_json = cdir / "source" / "pages.json"
    pages_dir = cdir / "source" / "pages"
    if pages_json.exists():
        console.print(f"already crawled ({pages_json}); delete it to crawl again")
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
    saved, used = [], set()
    for page in picked:
        try:
            markdown = (fc.scrape(page, formats=["markdown"]).markdown or "").strip()
            if not markdown:
                raise RuntimeError("no markdown returned")
        except Exception as e:
            console.print(f"  [yellow]skip[/yellow] {page}: {escape(str(e).splitlines()[0][:150])}")
            continue
        name = file_slug(page)
        while name in used:
            name += "-2"
        used.add(name)
        path = pages_dir / f"{name}.md"
        path.write_text(f"{page}\n\n{markdown}\n")
        saved.append({"url": page, "file": str(path.relative_to(cdir))})
        console.print(f"  saved {path.name} ({len(markdown):,} chars)  {page}")

    if not saved:
        fail("no pages could be scraped")
    pages_json.write_text(json.dumps(saved, indent=2))
    console.print(f"Crawled {len(saved)} pages -> {pages_json}")
