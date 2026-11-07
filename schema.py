"""Data contracts shared by every stage. Change a field here, update every stage that uses it.

Per client (clients/<slug>/):
  profile.json  BusinessProfile  facts found on the website (extract)
  pricing.json  PricingSheet     prices; only approved items are ever spoken (extract drafts, review approves)
  policy.json   FitPolicy        fit rules, hours, scheduling, emergencies (review, operator-confirmed)
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    found = "found"          # stated on the website, source_url set
    inferred = "inferred"    # reasonable reading of the site, not stated outright
    missing = "missing"      # not on the site
    operator = "operator"    # answered by the operator in review


class Fact(BaseModel):
    value: Optional[str] = None
    source_url: Optional[str] = None
    status: Status = Status.missing


class ListFact(BaseModel):
    value: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    status: Status = Status.missing


# ---------- What the website says ----------

class BusinessProfile(BaseModel):
    business_name: Fact = Field(default_factory=Fact)
    vertical: Fact = Field(default_factory=Fact)                 # hvac | plumbing | cleaning | other
    main_phone: Fact = Field(default_factory=Fact)
    service_area: ListFact = Field(default_factory=ListFact)     # cities or ZIPs as written on the site
    business_hours: Fact = Field(default_factory=Fact)
    emergency_policy: Fact = Field(default_factory=Fact)
    services_offered: ListFact = Field(default_factory=ListFact)
    services_not_offered: ListFact = Field(default_factory=ListFact)
    property_types: Fact = Field(default_factory=Fact)           # residential / commercial / both
    financing: Fact = Field(default_factory=Fact)
    licensed_insured: Fact = Field(default_factory=Fact)
    brands_serviced: ListFact = Field(default_factory=ListFact)
    warranty: Fact = Field(default_factory=Fact)
    payment_methods: ListFact = Field(default_factory=ListFact)
    faqs: ListFact = Field(default_factory=ListFact)
    staleness_signals: list[str] = Field(default_factory=list)   # old copyright, conflicting hours, old notices


REQUIRED_PROFILE_FIELDS = [
    "business_name", "vertical", "main_phone", "service_area",
    "business_hours", "services_offered",
]


# ---------- What the agent may say about price ----------

class PriceItem(BaseModel):
    service: str                                     # "Trip / diagnostic fee", "Water heater install"
    low: Optional[float] = None
    high: Optional[float] = None                     # low == high for a flat price
    unit: str = "per job"                            # per job | per hour | per visit | starting at
    notes: str = ""
    source: Literal["website", "operator"] = "website"
    source_url: Optional[str] = None
    approved: bool = False                           # ONLY approved items reach the agent


class PricingSheet(BaseModel):
    items: list[PriceItem] = Field(default_factory=list)
    share_prices: bool = True                        # operator can turn all price talk off
    financing_note: str = ""
    quote_rule: str = "These are estimates. The technician confirms the exact price on site before any work starts."


class ExtractionResult(BaseModel):
    """What the extract stage asks Claude for in one structured-output call."""
    profile: BusinessProfile
    price_items: list[PriceItem] = Field(default_factory=list)   # prices published on the site, approved=False


# ---------- Who the business serves, and when (operator-confirmed) ----------

class FitPolicy(BaseModel):
    service_zips: list[str] = Field(default_factory=list)
    service_cities: list[str] = Field(default_factory=list)
    services_offered: list[str] = Field(default_factory=list)
    services_not_offered: list[str] = Field(default_factory=list)
    residential: bool = True
    commercial: bool = False
    renters_ok: bool = True               # if True, agent notes the landlord may need to approve
    regular_hours: str = ""
    emergency_service: bool = False
    emergency_hours: str = ""             # "24/7", "until 10pm daily"
    typical_lead_time: str = ""           # "usually next business day"
    callback_promise: str = ""            # "someone will call you back within 1 business hour"
    owner_transfer_number: str = ""       # E.164, e.g. +14045551234 (used later for live transfer)
    notes: str = ""


# ---------- What every call should capture (used for ElevenLabs data collection) ----------

LEAD_FIELDS = {
    "caller_name": "Caller's full name",
    "callback_number": "Best phone number to call the caller back",
    "service_address": "Full street address where the work is needed",
    "zip_code": "5-digit ZIP code of the service address",
    "service_needed": "The problem or service requested, in the caller's words",
    "property_type": "residential or commercial; owner or renter",
    "urgency": "emergency, soon (this week), or flexible",
    "preferred_window": "Days and time window the caller prefers",
    "fit": "good, maybe, or not_a_fit, using the fit rules",
    "fit_reason": "One sentence on why",
    "price_discussed": "Any price range the agent shared, or none",
}


# ---------- What the operator learned on the call (discovery + onboarding intake) ----------

class FAQ(BaseModel):
    question: str
    answer: str


class Intake(BaseModel):
    # The business
    business_name: str = ""
    employee_count: str = ""            # as said: "8", "about 12", "3-5 crews"
    owner_name: str = ""
    owner_phone: str = ""
    owner_email: str = ""
    # Discovery call: today's process and pain
    who_answers_today: str = ""         # "owner's cell", "office manager until 5pm"
    scheduling_tool: str = ""           # Google Calendar, Jobber, Housecall Pro, paper
    # Baseline numbers (for the pitch math and the monthly report)
    missed_calls_per_week: Optional[float] = None
    booking_rate_pct: Optional[float] = None     # of 10 callers, how many book -> 60
    avg_job_value: Optional[float] = None
    monthly_call_volume: Optional[float] = None
    # How the agent should behave for this business
    will_not_quote: str = ""            # what they won't price over the phone/chat
    booking_rules: str = ""             # buffer times, crew capacity, lead time, job minimums
    faqs: list[FAQ] = Field(default_factory=list)
    lead_extra_fields: list[str] = Field(default_factory=list)   # beyond name/phone/address/issue/urgency
    notify: str = ""                    # who gets each lead and how ("text Mike at ...")
    escalation_rules: list[str] = Field(default_factory=list)    # what goes straight to a human
    brand_voice: str = ""               # casual/formal, phrases they use or avoid
    notes: str = ""                     # anything else from the call


def monthly_revenue_at_risk(intake: "Intake") -> Optional[float]:
    """Missed calls/week x share that would have booked x average job x 4.33 weeks."""
    if intake.missed_calls_per_week is None or intake.avg_job_value is None:
        return None
    rate = (intake.booking_rate_pct if intake.booking_rate_pct is not None else 100) / 100
    return intake.missed_calls_per_week * rate * intake.avg_job_value * 4.33
