"""Intake: merge what the website says with the operator's call notes into one record per client.

run(cdir, notes, basics):
  - notes: whatever the operator pasted (discovery answers, onboarding answers, a transcript).
  - basics: {"business_name", "employee_count"} typed into the form (may be blank).
  - ONE Claude call (claude-sonnet-5-5, structured output) fills intake.json and the starting values
    for policy.json and pricing.json. Rules: the owner's words in the notes beat the website; never
    invent facts, numbers or prices; prices from the notes come in UNAPPROVED (the operator ticks them).
  - With no notes, writes an intake with just the basics and website-based fit rules.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

import anthropic
from pydantic import BaseModel

import clients
import demo
from schema import FAQ, BusinessProfile, FitPolicy, Intake, PriceItem, PricingSheet

PRICE_RE = re.compile(r"\$\s*\d|\d\s*dollars?\b", re.I)   # FAQs reach the prompt unapproved

SYSTEM = """You turn a sales rep's notes from calls with a home-service business (HVAC, plumbing, roofing,
lawn care, cleaning) into the setup record for that business's AI receptionist.

You get: facts already pulled from the business's website, and the rep's raw notes (messy, abbreviated,
maybe a transcript). Fill every field you can.

Rules:
- The owner's words in the notes beat the website. Use website facts only where the notes are silent.
- Never invent a fact, number, price, phone number or email. Unknown -> empty string, empty list or null.
- Numbers: missed_calls_per_week, booking_rate_pct (percent of callers who book, e.g. "6 of 10" -> 60),
  avg_job_value (dollars), monthly_call_volume. Convert ranges to the midpoint.
- faqs: the 10-15 questions this business's customers ask most, each with the answer the business gives.
  Use answers stated in the notes or on the website only; skip a question if you don't know its answer.
  Never put a price or dollar amount in a faq; prices go only in price_items, which the operator approves.
- escalation_rules: situations that go straight to a human (emergencies, angry customers, big commercial
  jobs, anything the notes name). One short line each.
- brand_voice: one or two sentences on how they talk to customers, only if the notes say so.
- price_items: only prices the owner stated in the notes, as ranges (low/high), with unit and notes.
- service_zips: 5-digit ZIPs only. service_cities: as written, e.g. "Marietta, GA".
- regular_hours, emergency_service/emergency_hours, typical_lead_time, residential/commercial:
  from the notes, else the website, else leave empty/false.
- renters_ok: true/false only if the notes or website say whether they work for renters; else null."""


class _FAQ(BaseModel):
    question: str
    answer: str


class _Price(BaseModel):
    service: str
    low: Optional[float]
    high: Optional[float]
    unit: str
    notes: str


class _Draft(BaseModel):   # every field required: structured outputs rejects big all-optional models
    business_name: str
    employee_count: str
    owner_name: str
    owner_phone: str
    owner_email: str
    who_answers_today: str
    scheduling_tool: str
    missed_calls_per_week: Optional[float]
    booking_rate_pct: Optional[float]
    avg_job_value: Optional[float]
    monthly_call_volume: Optional[float]
    will_not_quote: str
    booking_rules: str
    faqs: list[_FAQ]
    lead_extra_fields: list[str]
    notify: str
    escalation_rules: list[str]
    brand_voice: str
    notes: str
    service_zips: list[str]
    service_cities: list[str]
    services_offered: list[str]
    services_not_offered: list[str]
    residential: bool
    commercial: bool
    renters_ok: Optional[bool]
    regular_hours: str
    emergency_service: bool
    emergency_hours: str
    typical_lead_time: str
    price_items: list[_Price]


def website_facts(profile: BusinessProfile) -> dict:
    out = {}
    for name, fact in profile:
        if hasattr(fact, "status") and fact.value:
            out[name] = fact.value
    if profile.staleness_signals:
        out["possibly_out_of_date"] = profile.staleness_signals
    return out


def run(cdir: Path, notes: str, basics: dict) -> None:
    profile_path = cdir / "profile.json"
    if not profile_path.exists():
        raise SystemExit("profile.json not found; read the website first.")
    profile = clients.load_model(profile_path, BusinessProfile)
    start_policy = demo.policy_from_profile(profile)
    start_policy.notes = ""
    start_policy.callback_promise = "Someone from our team will get back to you within one business hour."
    pricing_path = cdir / "pricing.json"
    pricing = clients.load_model(pricing_path, PricingSheet) if pricing_path.exists() else PricingSheet()

    if not notes.strip():
        intake = Intake(business_name=basics.get("business_name") or profile.business_name.value or "",
                        employee_count=basics.get("employee_count", ""))
        clients.save_model(cdir / "intake.json", intake)
        clients.save_model(cdir / "policy.json", start_policy)
        print("No call notes: intake has the basics only; fit rules come from the website.")
        _mark(cdir, intake)
        return

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set in .env")
    content = json.dumps({"typed_by_rep": basics, "website_facts": website_facts(profile),
                          "rep_notes": notes}, indent=1)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.parse(model="claude-sonnet-5-5", max_tokens=8000, system=SYSTEM,
                                 messages=[{"role": "user", "content": content}], output_format=_Draft)
    if resp.parsed_output is None:
        raise SystemExit(f"Claude returned no structured output (stop_reason={resp.stop_reason})")
    d = resp.parsed_output

    intake = Intake(
        business_name=basics.get("business_name") or d.business_name or profile.business_name.value or "",
        employee_count=basics.get("employee_count") or d.employee_count,
        owner_name=d.owner_name, owner_phone=d.owner_phone, owner_email=d.owner_email,
        who_answers_today=d.who_answers_today, scheduling_tool=d.scheduling_tool,
        missed_calls_per_week=d.missed_calls_per_week, booking_rate_pct=d.booking_rate_pct,
        avg_job_value=d.avg_job_value, monthly_call_volume=d.monthly_call_volume,
        will_not_quote=d.will_not_quote, booking_rules=d.booking_rules,
        faqs=[FAQ(question=f.question, answer=f.answer) for f in d.faqs if not PRICE_RE.search(f.answer)],
        lead_extra_fields=d.lead_extra_fields, notify=d.notify, escalation_rules=d.escalation_rules,
        brand_voice=d.brand_voice, notes=d.notes,
    )
    policy = FitPolicy(
        service_zips=[z for z in d.service_zips if z.strip().isdigit() and len(z.strip()) == 5]
        or start_policy.service_zips,
        service_cities=d.service_cities or start_policy.service_cities,
        services_offered=d.services_offered or start_policy.services_offered,
        services_not_offered=d.services_not_offered or start_policy.services_not_offered,
        residential=d.residential or start_policy.residential, commercial=d.commercial,
        renters_ok=start_policy.renters_ok if d.renters_ok is None else d.renters_ok,
        regular_hours=d.regular_hours or start_policy.regular_hours,
        emergency_service=d.emergency_service, emergency_hours=d.emergency_hours,
        typical_lead_time=d.typical_lead_time or "usually next business day",
        callback_promise=start_policy.callback_promise,
    )
    units = {"per job", "per hour", "per visit", "starting at"}
    new_prices = [PriceItem(service=p.service, low=p.low if p.low is not None else p.high,
                            high=p.high if p.high is not None else p.low,
                            unit=p.unit if p.unit in units else "per job", notes=p.notes,
                            source="operator", approved=False)
                  for p in d.price_items if p.low is not None or p.high is not None]
    have = {i.service.lower() for i in pricing.items}
    pricing = pricing.model_copy(update={"items": pricing.items + [p for p in new_prices
                                                                   if p.service.lower() not in have]})
    clients.save_model(cdir / "intake.json", intake)
    clients.save_model(cdir / "policy.json", policy)
    clients.save_model(pricing_path, pricing)
    print(f"Intake filled from the notes: {len(intake.faqs)} FAQs, {len(intake.escalation_rules)} "
          f"escalation rules, {len(new_prices)} prices to approve.")
    _mark(cdir, intake)


def _mark(cdir: Path, intake: Intake) -> None:
    clients.upsert(cdir.name, business_name=intake.business_name or None,
                   employee_count=intake.employee_count or None, reviewed_intake=False,
                   reviewed_facts=False, reviewed_policy=False, reviewed_prices=False)
