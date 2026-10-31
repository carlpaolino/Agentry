"""Stage 2 - extract: pages -> profile.json + draft pricing.json.

run(cdir):
  - Read every cdir/source/pages/*.md (each starts with its URL).
  - ONE Claude call (model "claude-sonnet-5-5") with structured output = schema.ExtractionResult.
    Prompt rules: cite source_url for every found value; status "missing" rather than guess;
    copy prices only if the site states them (low/high/unit/notes), approved=False, source="website";
    list anything that looks out of date in staleness_signals.
  - Save cdir/profile.json (BusinessProfile) and cdir/pricing.json (PricingSheet with those items).
    If pricing.json already exists with approved items, do NOT overwrite it.
  - clients.upsert(slug, business_name=..., vertical=...).
  - Print a rich table: field, value (truncated to 60 chars), status (green found, yellow inferred, red missing).
"""
from pathlib import Path


def run(cdir: Path) -> None:
    raise NotImplementedError("extract: see CURSOR_PROMPTS.md, Prompt 3")
