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
from pathlib import Path


def run(url: str, cdir: Path) -> None:
    raise NotImplementedError("crawl: see CURSOR_PROMPTS.md, Prompt 2")
