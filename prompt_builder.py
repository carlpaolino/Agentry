"""Stage 4 - prompt: profile + policy + pricing -> the agent's instructions.

run(cdir):
  - Load profile.json, policy.json, pricing.json.
  - Render templates/base.md with string.Template.substitute (NOT format; prices contain "$").
    $emergency_rules comes from templates/emergencies/<vertical>.md (fallback hvac.md).
  - $price_list: ONLY items with approved=True, one bullet each, e.g.
    "- Water heater install: $1,200 to $2,400 per job (tank units only)". If share_prices is False
    or nothing is approved: "No prices are approved. Never give a price; say the team will quote."
  - Any blank value renders as "Not listed. Say the team will confirm."
  - Fail loudly if any "$name" placeholder is left in the output.
  - Write cdir/agent/prompt.md and cdir/agent/first_message.txt.
"""
import re
import sys
from pathlib import Path
from string import Template

from rich.console import Console
from rich.markup import escape

import clients
from schema import BusinessProfile, FitPolicy, PriceItem, PricingSheet

TEMPLATES = Path("templates")
BLANK = "Not listed. Say the team will confirm."
NO_PRICES = "No prices are approved. Never give a price; say the team will quote."
VERTICAL_WORDS = {"hvac": "HVAC", "plumbing": "plumbing", "cleaning": "cleaning", "other": "home-service"}
console = Console(highlight=False, soft_wrap=True)


def fail(message: str) -> None:
    console.print(f"[red]prompt failed:[/red] {escape(message)}")
    sys.exit(1)


def text(value) -> str:
    if isinstance(value, list):
        value = ", ".join(v.strip() for v in value if v and v.strip())
    return (value or "").strip() or BLANK


def money(x: float) -> str:
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def price_line(item: PriceItem) -> str:
    low = item.low if item.low is not None else item.high
    high = item.high if item.high is not None else item.low
    if low is None:
        return ""
    if item.unit == "starting at":
        amount = f"starting at {money(low)}"
    elif low == high:
        amount = f"{money(low)} flat" if item.unit == "per job" else f"{money(low)} {item.unit}"
    else:
        amount = f"{money(low)} to {money(high)} {item.unit}"
    notes = f" ({item.notes.strip()})" if item.notes.strip() else ""
    return f"- {item.service}: {amount}{notes}"


def price_list(pricing: PricingSheet) -> str:
    if not pricing.share_prices:
        return NO_PRICES
    lines = [price_line(i) for i in pricing.items if i.approved]
    lines = [l for l in lines if l]
    return "\n".join(lines) if lines else NO_PRICES


def property_types(policy: FitPolicy) -> str:
    if policy.residential and policy.commercial:
        return "Homes and businesses"
    if policy.residential:
        return "Homes only"
    if policy.commercial:
        return "Businesses only"
    return BLANK


def emergency_rules(vertical: str) -> str:
    path = TEMPLATES / "emergencies" / f"{vertical}.md"
    if not path.exists():
        path = TEMPLATES / "emergencies" / "hvac.md"
    return path.read_text().strip()


def run(cdir: Path) -> None:
    paths = {name: cdir / f"{name}.json" for name in ("profile", "policy", "pricing")}
    for name in ("profile", "policy"):
        if not paths[name].exists():
            stage = "extract" if name == "profile" else "review"
            fail(f"{paths[name]} not found; run the {stage} stage first.")
    profile = clients.load_model(paths["profile"], BusinessProfile)
    policy = clients.load_model(paths["policy"], FitPolicy)
    pricing = (clients.load_model(paths["pricing"], PricingSheet) if paths["pricing"].exists()
               else PricingSheet())

    rec = clients.get_client(cdir.name) or {}
    business_name = profile.business_name.value or rec.get("business_name") or ""
    if not business_name:
        fail("no business name in profile.json or the registry")
    vertical = (profile.vertical.value or rec.get("vertical") or "other").lower()

    if policy.emergency_service:
        emergency_line = f"Yes, {policy.emergency_hours}" if policy.emergency_hours.strip() else "Yes"
        emergency_close = "I'm marking this urgent so the team is alerted right away."
    else:
        emergency_line = "No emergency service. Take details and mark URGENT for the team."
        emergency_close = "I'm marking this urgent. The team will call you back as soon as they're available."
    renters_note = ("- Renters: take the details and mention the landlord may need to approve the work."
                    if policy.renters_ok else
                    "- Renters: we only work directly with property owners; ask them to have the owner call.")

    values = {
        "business_name": business_name,
        "vertical": VERTICAL_WORDS.get(vertical, vertical),
        "main_phone": text(profile.main_phone.value),
        "regular_hours": text(policy.regular_hours or profile.business_hours.value),
        "emergency_line": emergency_line,
        "service_zips": text(policy.service_zips),
        "service_cities": text(policy.service_cities),
        "services_offered": text(policy.services_offered),
        "services_not_offered": text(policy.services_not_offered),
        "property_types": property_types(policy),
        "typical_lead_time": text(policy.typical_lead_time),
        "financing_note": text(pricing.financing_note or profile.financing.value),
        "licensed_insured": text(profile.licensed_insured.value),
        "brands_serviced": text(profile.brands_serviced.value),
        "warranty": text(profile.warranty.value),
        "payment_methods": text(profile.payment_methods.value),
        "faqs": text(profile.faqs.value),
        "callback_promise": text(policy.callback_promise),
        "renters_note": renters_note,
        "price_list": price_list(pricing),
        "quote_rule": text(pricing.quote_rule),
        "emergency_rules": emergency_rules(vertical),
        "emergency_close": emergency_close,
    }
    try:
        prompt = Template((TEMPLATES / "base.md").read_text()).substitute(values)
    except (KeyError, ValueError) as e:
        fail(f"templates/base.md has a placeholder with no value: {e}")
    leftover = sorted(set(re.findall(r"\$[a-z_]+", prompt)))
    if leftover:
        fail(f"placeholders left in prompt.md: {', '.join(leftover)}")

    first_message = (f"Thanks for calling {business_name}! I'm the AI assistant. "
                     "I can help get you taken care of. What's going on?")
    agent_dir = cdir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "prompt.md").write_text(prompt)
    (agent_dir / "first_message.txt").write_text(first_message + "\n")
    approved = 0 if price_list(pricing) == NO_PRICES else price_list(pricing).count("\n") + 1
    console.print(f"Wrote {agent_dir / 'prompt.md'} ({len(prompt):,} chars, {approved} approved prices)")
    console.print(f"Wrote {agent_dir / 'first_message.txt'}")
