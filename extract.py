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
import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, create_model
from rich.console import Console
from rich.markup import escape
from rich.table import Table

import clients
from schema import (REQUIRED_PROFILE_FIELDS, BusinessProfile, ExtractionResult, Fact, ListFact,
                    PricingSheet, Status)

VERTICALS = {"hvac", "plumbing", "cleaning", "other"}


# Structured outputs rejects ExtractionResult as "too complex" because every field has a default
# (each one counts as optional). The request uses this all-required mirror, then converts back.
class _Fact(BaseModel):
    value: Optional[str]
    source_url: Optional[str]
    status: Status


class _ListFact(BaseModel):
    value: list[str]
    source_url: Optional[str]
    status: Status


class _Price(BaseModel):
    service: str
    low: Optional[float]
    high: Optional[float]
    unit: Literal["per job", "per hour", "per visit", "starting at"]
    notes: str
    source_url: Optional[str]


_Profile = create_model("Profile", **{
    name: ((_ListFact if f.annotation is ListFact else _Fact if f.annotation is Fact
            else f.annotation), ...)
    for name, f in BusinessProfile.model_fields.items()
})


class _Extraction(BaseModel):
    profile: _Profile
    price_items: list[_Price]

STATUS_COLORS = {"found": "green", "inferred": "yellow", "missing": "red", "operator": "cyan"}
console = Console(highlight=False, soft_wrap=True)

SYSTEM = """You extract facts about a home-service business (HVAC, plumbing, cleaning) from its website pages.
The facts will brief a phone receptionist, so a wrong fact is worse than a missing one.

Rules:
- Use only what the pages state. If a fact isn't there, set status "missing" and value null (empty list for list fields). Never guess or fill in from general knowledge.
- Every found value cites the page URL it came from in source_url. Each page begins with its URL on the first line.
- Use status "found" when a page states the fact outright, and "inferred" only for a close, reasonable reading of what a page says.
- vertical must be one of: hvac, plumbing, cleaning, other.
- service_area: cities, counties or ZIP codes exactly as the site lists them.
- Prices: copy only prices the site states, with low/high/unit/notes, approved=false, source="website", and source_url. For a flat price set low and high to the same number. unit is one of: per job, per hour, per visit, starting at. unit is one of: per job, per hour, per visit, starting at. unit is one of: per job, per hour, per visit, starting at. Put conditions (e.g. "new customers only", "expires 12/31") in notes. Never estimate a price. Discounts and coupons without a stated price are not prices.
- staleness_signals: footer copyright year before 2025, hours that differ between pages, expired promotions, old notices. Each one a short sentence naming the page."""


def fail(message: str) -> None:
    console.print(f"[red]extract failed:[/red] {escape(message)}")
    sys.exit(1)


def load_pages(cdir: Path) -> str:
    files = sorted((cdir / "source" / "pages").glob("*.md"))
    if not files:
        fail(f"no pages in {cdir / 'source' / 'pages'}; run the crawl stage first.")
    parts = []
    for f in files:
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", f.read_text())
        parts.append(f"<page>\n{text.strip()}\n</page>")
    console.print(f"Read {len(files)} pages ({sum(len(p) for p in parts):,} chars)")
    return "\n\n".join(parts)


def show(result: ExtractionResult) -> None:
    t = Table("field", "value", "status")
    for name, fact in result.profile:
        if not hasattr(fact, "status"):
            continue
        value = fact.value
        text = ", ".join(value) if isinstance(value, list) else (value or "")
        text = text if len(text) <= 60 else text[:57] + "..."
        color = STATUS_COLORS[fact.status.value]
        label = f"{name} *" if name in REQUIRED_PROFILE_FIELDS else name
        t.add_row(label, escape(text), f"[{color}]{fact.status.value}[/{color}]")
    console.print(t)
    console.print("* required")
    for s in result.profile.staleness_signals:
        console.print(f"[yellow]stale?[/yellow] {escape(s)}")


def run(cdir: Path) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        fail("ANTHROPIC_API_KEY is not set in .env")
    pages = load_pages(cdir)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        resp = client.messages.parse(
            model="claude-sonnet-5-5",
            max_tokens=12000,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Website pages:\n\n{pages}"}],
            output_format=_Extraction,
        )
    except Exception as e:
        fail(f"Claude call: {type(e).__name__}: {e}")
    if resp.parsed_output is None:
        fail(f"Claude returned no structured output (stop_reason={resp.stop_reason})")
    result = ExtractionResult.model_validate(resp.parsed_output.model_dump())

    vertical = (result.profile.vertical.value or "").strip().lower()
    if vertical and vertical not in VERTICALS:
        result.profile.vertical = Fact(value="other", source_url=result.profile.vertical.source_url,
                                       status=Status.inferred)
    for item in result.price_items:
        item.approved = False
        item.source = "website"

    clients.save_model(cdir / "profile.json", result.profile)
    console.print(f"Saved {cdir / 'profile.json'}")

    pricing_path = cdir / "pricing.json"
    if pricing_path.exists() and any(
        i.approved for i in clients.load_model(pricing_path, PricingSheet).items
    ):
        console.print(f"[yellow]Kept {pricing_path}: it already has approved prices[/yellow]")
    else:
        clients.save_model(pricing_path, PricingSheet(items=result.price_items))
        console.print(f"Saved {pricing_path} ({len(result.price_items)} draft prices)")

    clients.upsert(cdir.name, business_name=result.profile.business_name.value,
                   vertical=result.profile.vertical.value)
    show(result)
