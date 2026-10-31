"""Stage 3 - review: the operator fills gaps, confirms fit rules, approves prices. Target: under 5 minutes.

run(cdir), three parts, all in the terminal with rich.prompt (Enter accepts the shown default):
  A. Missing facts: in plain code, list REQUIRED_PROFILE_FIELDS with status missing + staleness_signals.
     One Claude call phrases them as at most 6 grouped plain-English questions. Answers update
     profile.json with status "operator".
  B. Fit policy: a FIXED questionnaire (no AI), defaults pre-filled from profile.json:
     service ZIPs and cities, services offered / not offered, residential?, commercial?, renters ok?,
     regular hours, emergency service? + hours, typical lead time, callback promise,
     owner transfer number. Save policy.json (FitPolicy).
  C. Pricing: ask "Should the agent share any prices?" -> share_prices. If yes, show each draft
     PriceItem; operator chooses approve / edit / delete; then may add items (source="operator",
     approved=True). Always ask for the trip/diagnostic fee and the financing note. Save pricing.json.
  - Save every raw answer to cdir/answers.json. If policy.json exists, ask "Redo review? (y/N)" and
    return on N.
"""
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.table import Table

import clients
from schema import (REQUIRED_PROFILE_FIELDS, BusinessProfile, FitPolicy, ListFact, PriceItem,
                    PricingSheet, Status)

MAX_QUESTIONS = 6
UNITS = ["per job", "per hour", "per visit", "starting at"]
DEFAULT_CALLBACK = "Someone from our team will call you back within one business hour."
DEFAULT_LEAD_TIME = "usually next business day"
SKIP = "skip"
console = Console(highlight=False, soft_wrap=True)

QUESTION_SYSTEM = """You help an operator set up a phone receptionist for a home-service business.
You get facts missing from the business's website and signs that the site may be out of date.
Write at most 6 short, plain-English questions for the business owner, grouping related items.
For each question, list the profile field names it fills, using only names from the allowed list.
For an out-of-date sign that doesn't fill a field (for example conflicting years in business), use an empty list."""


class Question(BaseModel):
    question: str
    fields: list[str]


class Questions(BaseModel):
    questions: list[Question]


def fail(message: str) -> None:
    console.print(f"[red]review failed:[/red] {escape(message)}")
    sys.exit(1)


def ask(label: str, default: str) -> str:
    return Prompt.ask(label, default=default, console=console).strip()


def split(text: str, sep: str = ",") -> list[str]:
    return [p.strip() for p in text.split(sep) if p.strip()]


def fact_text(fact) -> str:
    v = fact.value
    return "; ".join(v) if isinstance(v, list) else (v or "")


# ---------- Part A ----------

def write_questions(profile: BusinessProfile, gaps: list[str]) -> list[Question]:
    allowed = [n for n, v in profile if hasattr(v, "status")]
    current = {n: fact_text(getattr(profile, n)) for n in allowed if getattr(profile, n).value}
    content = json.dumps({
        "business": profile.business_name.value,
        "missing_required_fields": gaps,
        "out_of_date_signs": profile.staleness_signals,
        "allowed_fields": allowed,
        "current_values": current,
    }, indent=1)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.parse(
        model="claude-haiku-5-5", max_tokens=1500, system=QUESTION_SYSTEM,
        messages=[{"role": "user", "content": content}], output_format=Questions,
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"no structured output (stop_reason={resp.stop_reason})")
    questions = resp.parsed_output.questions[:MAX_QUESTIONS]
    for q in questions:
        q.fields = [f for f in q.fields if f in allowed]
    covered = {f for q in questions for f in q.fields}
    for g in gaps:
        if g not in covered:
            questions.append(Question(question=f"What should the agent know about: {g.replace('_', ' ')}?",
                                      fields=[g]))
    return questions


def part_a(profile: BusinessProfile, answers: dict) -> list[str]:
    console.rule("A. Missing facts")
    gaps = [f for f in REQUIRED_PROFILE_FIELDS if getattr(profile, f).status == Status.missing]
    notes = []
    if not gaps and not profile.staleness_signals:
        console.print("Nothing missing from the website.")
        return notes
    console.print(f"Missing: {', '.join(gaps) or 'none'}; out-of-date signs: {len(profile.staleness_signals)}")
    try:
        questions = write_questions(profile, gaps)
    except Exception as e:
        fail(f"writing questions with Claude: {type(e).__name__}: {e}")
    console.print(f'Type "{SKIP}" or press Enter on {SKIP} to leave a field as it is.')
    for i, q in enumerate(questions, 1):
        console.print(f"\n[bold]{i}. {escape(q.question)}[/bold]")
        if not q.fields:
            reply = ask("  answer", SKIP)
            answers["A"].append({"question": q.question, "answer": reply})
            if reply.lower() != SKIP:
                notes.append(f"{q.question} {reply}")
            continue
        for field in q.fields:
            fact = getattr(profile, field)
            reply = ask(f"  {field}", fact_text(fact) or SKIP)
            answers["A"].append({"question": q.question, "field": field, "answer": reply})
            if reply.lower() == SKIP or reply == fact_text(fact):
                continue
            if isinstance(fact, ListFact):
                value = split(reply, ";" if ";" in reply else ",")
            else:
                value = reply
            setattr(profile, field, type(fact)(value=value, status=Status.operator))
    return notes


# ---------- Part B ----------

def ask_zips(default: list[str], answers: dict) -> list[str]:
    while True:
        reply = ask("Service ZIP codes (comma-separated)", ", ".join(default))
        zips = split(reply)
        bad = [z for z in zips if not re.fullmatch(r"\d{5}", z)]
        if bad:
            console.print(f"[red]Not 5-digit ZIPs:[/red] {escape(', '.join(bad))}")
            continue
        answers["B"]["service_zips"] = reply
        return zips


def ask_phone(answers: dict) -> str:
    while True:
        reply = ask("Owner transfer number, E.164 like +14045551234 (blank for none)", "")
        if not reply or re.fullmatch(r"\+[1-9]\d{7,14}", reply):
            answers["B"]["owner_transfer_number"] = reply
            return reply
        console.print("[red]Use E.164: + then country code and number, no spaces.[/red]")


def part_b(profile: BusinessProfile, answers: dict, notes: list[str]) -> FitPolicy:
    console.rule("B. Who the business serves")
    area = profile.service_area.value
    site_zips = [a for a in area if re.fullmatch(r"\d{5}", a)]
    site_cities = [a for a in area if a not in site_zips]
    property_text = (profile.property_types.value or "").lower()
    emergency_text = (profile.emergency_policy.value or "").lower()
    has_emergency = "24/7" in emergency_text or "24 hours" in emergency_text or "emergency" in emergency_text
    b = answers["B"]

    def text(key, label, default):
        b[key] = ask(label, default)
        return b[key]

    def yes(key, label, default):
        b[key] = Confirm.ask(label, default=default, console=console)
        return b[key]

    zips = ask_zips(site_zips, answers)
    cities = split(text("service_cities", "Service cities (comma-separated)", ", ".join(site_cities)))
    offered = split(text("services_offered", "Services offered (separate with ;)",
                         "; ".join(profile.services_offered.value)), ";")
    not_offered = split(text("services_not_offered", "Services NOT offered (separate with ;)",
                             "; ".join(profile.services_not_offered.value)), ";")
    residential = yes("residential", "Serves homes?",
                      not property_text or any(w in property_text for w in ("residential", "home")))
    commercial = yes("commercial", "Serves businesses?",
                     any(w in property_text for w in ("commercial", "business")))
    renters_ok = yes("renters_ok", "OK to take jobs from renters?", True)
    hours = text("regular_hours", "Regular hours", profile.business_hours.value or "")
    emergency = yes("emergency_service", "Offers emergency service?", has_emergency)
    emergency_hours = ""
    if emergency:
        emergency_hours = text("emergency_hours", "Emergency hours",
                               "24/7" if ("24/7" in emergency_text or "24 hours" in emergency_text) else "")
    lead = text("typical_lead_time", "Typical wait for a visit", DEFAULT_LEAD_TIME)
    callback = text("callback_promise", "Callback promise (said at the end of every call)", DEFAULT_CALLBACK)
    transfer = ask_phone(answers)

    return FitPolicy(
        service_zips=zips, service_cities=cities, services_offered=offered,
        services_not_offered=not_offered, residential=residential, commercial=commercial,
        renters_ok=renters_ok, regular_hours=hours, emergency_service=emergency,
        emergency_hours=emergency_hours, typical_lead_time=lead, callback_promise=callback,
        owner_transfer_number=transfer, notes=" ".join(notes),
    )


# ---------- Part C ----------

def money(x) -> str:
    return "" if x is None else f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def price_text(item: PriceItem) -> str:
    if item.low is None and item.high is None:
        return "(no amount)"
    if item.high is None or item.low == item.high:
        return f"{money(item.low if item.low is not None else item.high)} {item.unit}"
    return f"{money(item.low)} to {money(item.high)} {item.unit}"


def parse_amount(text: str):
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
    if not nums:
        return None, None
    return nums[0], nums[-1]


def show_prices(items: list[PriceItem]) -> None:
    t = Table("#", "service", "price", "notes", "source", "approved")
    for i, it in enumerate(items, 1):
        t.add_row(str(i), escape(it.service), escape(price_text(it)), escape(it.notes[:50]), it.source,
                  "[green]yes[/green]" if it.approved else "[red]no[/red]")
    console.print(t if items else "No draft prices.")


def edit_item(item: PriceItem, answers: dict, approved_default: bool) -> PriceItem:
    service = ask("  Service", item.service)
    current = "" if item.low is None else (f"{item.low:g}" if item.low == item.high or item.high is None
                                           else f"{item.low:g}-{item.high:g}")
    while True:
        amount = ask("  Price (e.g. 89 or 1200-2400)", current)
        low, high = parse_amount(amount)
        if low is not None:
            break
        console.print("[red]Enter a number or a range.[/red]")
    unit = Prompt.ask("  Unit", choices=UNITS, default=item.unit if item.unit in UNITS else "per job",
                      console=console)
    notes = ask("  Notes (blank for none)", item.notes)
    approved = Confirm.ask("  Approve this price?", default=approved_default, console=console)
    answers["C"].append({"service": service, "price": amount, "unit": unit, "notes": notes,
                         "approved": approved})
    return item.model_copy(update={"service": service, "low": low, "high": high, "unit": unit,
                                   "notes": notes, "approved": approved})


def part_c(profile: BusinessProfile, pricing: PricingSheet, answers: dict) -> PricingSheet:
    console.rule("C. Prices")
    items = list(pricing.items)
    share = Confirm.ask("Should the agent share any prices?", default=True, console=console)
    answers["C"].append({"share_prices": share})
    if share:
        console.print('Type numbers to approve (e.g. "1 3"), "e 2" to edit, "d 3" to delete, '
                      '"a" to add, Enter to finish.')
        while True:
            show_prices(items)
            cmd = ask("Prices", "").lower()
            answers["C"].append({"command": cmd})
            if not cmd:
                break
            parts = cmd.replace(",", " ").split()
            nums = [int(p) - 1 for p in parts if p.isdigit()]
            if any(not 0 <= n < len(items) for n in nums):
                console.print("[red]No item with that number.[/red]")
            elif parts[0] == "a":
                items.append(edit_item(PriceItem(service="", source="operator"), answers, True)
                             .model_copy(update={"source": "operator", "approved": True}))
            elif parts[0] == "e" and len(nums) == 1:
                items[nums[0]] = edit_item(items[nums[0]], answers, True)
            elif parts[0] == "d" and len(nums) == 1:
                console.print(f"Deleted {escape(items.pop(nums[0]).service)}")
            elif nums and all(p.isdigit() for p in parts):
                for n in nums:
                    items[n].approved = True
            else:
                console.print("[red]Didn't understand that.[/red]")

        if not any(re.search(r"trip|diagnos|service call", i.service, re.I) for i in items):
            fee = ask("Trip / diagnostic fee (e.g. 89, blank for none)", "")
            answers["C"].append({"trip_fee": fee})
            low, high = parse_amount(fee)
            if low is not None:
                items.append(PriceItem(service="Trip / diagnostic fee", low=low, high=high,
                                       unit="per visit", source="operator", approved=True))

    financing = ask("Financing note for callers (blank for none)",
                    pricing.financing_note or profile.financing.value or "")
    answers["C"].append({"financing_note": financing})
    return pricing.model_copy(update={"items": items, "share_prices": share, "financing_note": financing})


# ---------- Summary ----------

def summary(profile: BusinessProfile, policy: FitPolicy, pricing: PricingSheet) -> None:
    console.rule("Summary")
    props = " and ".join(p for p, on in (("homes", policy.residential), ("businesses", policy.commercial)) if on)
    console.print(f"ZIPs: {len(policy.service_zips)} | cities: {len(policy.service_cities)} | "
                  f"services: {len(policy.services_offered)} offered, {len(policy.services_not_offered)} not offered")
    console.print(f"Serves: {props or 'nobody (check this)'} | renters ok: {'yes' if policy.renters_ok else 'no'}")
    console.print(f"Hours: {escape(policy.regular_hours or '-')} | emergency: "
                  f"{escape(policy.emergency_hours or 'yes') if policy.emergency_service else 'no'} | "
                  f"wait: {escape(policy.typical_lead_time or '-')}")
    console.print(f"Callback: {escape(policy.callback_promise or '-')} | transfer: {policy.owner_transfer_number or 'none'}")

    approved = [i for i in pricing.items if i.approved] if pricing.share_prices else []
    console.print(f"Approved prices ({len(approved)}):" if approved else
                  "Approved prices: none, so the agent will say the team will quote.")
    for i in approved:
        console.print(f"  - {escape(i.service)}: {escape(price_text(i))}" + (f" ({escape(i.notes)})" if i.notes else ""))

    covered_by_policy = {"service_area", "business_hours", "services_offered"}
    missing = [f for f in REQUIRED_PROFILE_FIELDS
               if f not in covered_by_policy and getattr(profile, f).status == Status.missing]
    missing += [label for label, empty in (
        ("service ZIPs", not policy.service_zips), ("regular hours", not policy.regular_hours),
        ("services offered", not policy.services_offered), ("callback promise", not policy.callback_promise),
    ) if empty]
    console.print(f"[yellow]Still missing: {', '.join(dict.fromkeys(missing))}[/yellow]" if missing
                  else "[green]Nothing required is missing.[/green]")


def run(cdir: Path) -> None:
    profile_path, policy_path = cdir / "profile.json", cdir / "policy.json"
    pricing_path, answers_path = cdir / "pricing.json", cdir / "answers.json"
    if not profile_path.exists():
        fail(f"{profile_path} not found; run the extract stage first.")
    if policy_path.exists() and not Confirm.ask("Redo review?", default=False, console=console):
        console.print("Kept the existing review.")
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        fail("ANTHROPIC_API_KEY is not set in .env")

    profile = clients.load_model(profile_path, BusinessProfile)
    pricing = clients.load_model(pricing_path, PricingSheet) if pricing_path.exists() else PricingSheet()
    answers = {"A": [], "B": {}, "C": []}

    notes = part_a(profile, answers)
    clients.save_model(profile_path, profile)
    policy = part_b(profile, answers, notes)
    clients.save_model(policy_path, policy)
    pricing = part_c(profile, pricing, answers)
    clients.save_model(pricing_path, pricing)
    answers_path.write_text(json.dumps(answers, indent=2))
    console.print(f"Saved {profile_path.name}, {policy_path.name}, {pricing_path.name}, {answers_path.name}")
    summary(profile, policy, pricing)
