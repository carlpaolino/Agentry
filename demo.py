"""Demo mode: website -> an agent the owner can talk to in a few minutes, with no review.

Used on cold calls, before the business has agreed to anything. Built to be safe without a human check:
  - uses only facts found on the website (unknowns become "the team will confirm")
  - shares NO prices, even ones on the website
  - promises nothing beyond "the team will call you back"
After a sale, onboarding (the dashboard's review tabs) replaces this with owner-confirmed facts.
"""
import re
from pathlib import Path

import clients
from schema import BusinessProfile, FitPolicy, PricingSheet

DEMO_CALLBACK = "Someone from our team will call you back shortly to confirm."
DEMO_NOTE = "DEMO: built from the website only; not reviewed by the business owner."


def policy_from_profile(profile: BusinessProfile) -> FitPolicy:
    """Best-guess fit rules from the website. Onboarding uses these as the form's starting values."""
    area = profile.service_area.value
    zips = [a for a in area if re.fullmatch(r"\d{5}", a.strip())]
    cities = [a for a in area if a not in zips]
    props = (profile.property_types.value or "").lower()
    emerg = (profile.emergency_policy.value or "").lower()
    round_clock = "24/7" in emerg or "24 hours" in emerg
    return FitPolicy(
        service_zips=zips,
        service_cities=cities,
        services_offered=profile.services_offered.value,
        services_not_offered=profile.services_not_offered.value,
        residential=not props or any(w in props for w in ("residential", "home")),
        commercial=any(w in props for w in ("commercial", "business")),
        renters_ok=True,
        regular_hours=profile.business_hours.value or "",
        emergency_service=round_clock or "emergency" in emerg,
        emergency_hours="24/7" if round_clock else "",
        typical_lead_time="",
        callback_promise=DEMO_CALLBACK,
        notes=DEMO_NOTE,
    )


def prepare(cdir: Path) -> None:
    """Stands in for the review stage in demo mode: writes policy.json and turns prices off."""
    profile_path = cdir / "profile.json"
    if not profile_path.exists():
        raise SystemExit(f"{profile_path} not found; run the extract stage first.")
    profile = clients.load_model(profile_path, BusinessProfile)
    clients.save_model(cdir / "policy.json", policy_from_profile(profile))

    pricing_path = cdir / "pricing.json"
    pricing = clients.load_model(pricing_path, PricingSheet) if pricing_path.exists() else PricingSheet()
    clients.save_model(pricing_path, pricing.model_copy(update={"share_prices": False}))

    clients.upsert(cdir.name, mode="demo", reviewed_facts=False, reviewed_policy=False,
                   reviewed_prices=False)
    print("Demo rules written from the website (no prices, no owner review).")
