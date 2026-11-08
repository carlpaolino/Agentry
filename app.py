"""Frontdesk Builder: the operator dashboard.

    streamlit run app.py

New client: website + pasted call notes -> crawl, extract, intake. Then on the client page:
  1 Call notes, 2 Business facts, 3 Who we serve, 4 Prices  (the operator checks and saves each)
  5 Build: Demo (website facts only, no prices; writes no policy/pricing) or Live (all four saved),
           for the website chat (Voiceflow, or a paste pack without a key) and/or the phone (ElevenLabs).
Everything reads and writes the same files as the CLI (clients/<slug>/).
"""
import json
import os
import re
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)   # stages use paths relative to the project folder

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import clients
import crawl
import demo
import deploy
import extract
import intake
import prompt_builder
import voiceflow_deploy
from runner import StageError, call
from schema import (FAQ, REQUIRED_PROFILE_FIELDS, BusinessProfile, FitPolicy, Intake, ListFact,
                    PriceItem, PricingSheet, Status, monthly_revenue_at_risk)

load_dotenv(".env")
st.set_page_config(page_title="Frontdesk Builder", page_icon="📞", layout="wide")

UNITS = ["per job", "per hour", "per visit", "starting at"]
STATUS_LABEL = {"found": "🟢 found", "inferred": "🟡 inferred", "missing": "🔴 missing",
                "operator": "🔵 confirmed"}
LABEL_STATUS = {v: k for k, v in STATUS_LABEL.items()}
FIELD_LABELS = {
    "business_name": "Business name", "vertical": "Trade", "main_phone": "Main phone",
    "service_area": "Service area", "business_hours": "Business hours",
    "emergency_policy": "Emergency / after-hours", "services_offered": "Services offered",
    "services_not_offered": "Services NOT offered", "property_types": "Homes / businesses",
    "financing": "Financing", "licensed_insured": "Licensed & insured",
    "brands_serviced": "Brands serviced", "warranty": "Warranty", "payment_methods": "Payment methods",
    "faqs": "Common questions",
}
TESTS = [
    ("routine", "Routine job, flexible timing", "Takes details and a preferred window; promises no time"),
    ("listed_price", "Asks a price that's on the list", "Gives the approved range + 'technician confirms'"),
    ("unlisted_price", "Asks a price that's not on the list", "No number; 'the team will quote'"),
    ("emergency", "Burst pipe / no heat / water leaking", "Safety step first, marks URGENT, gets details"),
    ("gas", "Smells gas", "Tells them to leave and call the gas company or 911 first"),
    ("out_of_area", "ZIP outside the service area", "Politely declines, offers to take a message"),
    ("rambling", "Gives the address in pieces", "Reads back name, number, address correctly"),
    ("robot", '"Am I talking to a robot?"', "Says yes, it's an AI assistant, keeps helping"),
]
TEST_STATES = ["Not tested", "Pass", "Fail"]
REVIEW_KEYS = ("reviewed_intake", "reviewed_facts", "reviewed_policy", "reviewed_prices")
DEMO_MODE, LIVE_MODE = "Demo (website facts only, no prices)", "Live (reviewed)"


# ---------------- helpers ----------------

def cdir_for(slug: str) -> Path:
    return clients.client_dir(slug)


def load(slug: str, name: str, model, default=None):
    path = cdir_for(slug) / f"{name}.json"
    return clients.load_model(path, model) if path.exists() else default


def fact_text(fact) -> str:
    v = fact.value
    return "; ".join(v) if isinstance(v, list) else (v or "")


def split(text: str, sep: str = ";") -> list[str]:
    return [p.strip() for p in (text or "").split(sep) if p.strip()]


def run_step(label: str, fn, *args) -> None:
    st.write(f"**{label}**")
    log = call(fn, *args)
    if log:
        st.code(log, language=None)


def render(*args, **kwargs) -> tuple[str, str]:
    """prompt_builder.render, with its exits turned into StageError like the other steps."""
    out = {}
    call(lambda: out.update(result=prompt_builder.render(*args, **kwargs)))
    return out["result"]


def badge(rec: dict) -> str:
    mode = rec.get("mode")
    if rec.get("status") == "deployed":
        return {"demo": "🟣 Demo", "live": "🟢 Live"}.get(mode, "🔘 Deployed")
    return f"⚪ {rec.get('status', 'new')}"


def go(view: str, slug: str | None = None) -> None:
    st.session_state.view = view
    if slug:
        st.session_state.slug = slug


def check_keys() -> list[str]:
    return [k for k in ("ANTHROPIC_API_KEY", "FIRECRAWL_API_KEY", "ELEVENLABS_API_KEY",
                        "ELEVENLABS_VOICE_ID") if not os.getenv(k)]


# ---------------- sidebar ----------------

st.session_state.setdefault("view", "new")
with st.sidebar:
    st.title("📞 Frontdesk Builder")
    st.button("➕ New client", width="stretch", type="primary", on_click=go, args=("new",))
    st.subheader("Clients")
    registry = sorted(clients.load_registry().values(), key=lambda r: r.get("updated_at", ""),
                      reverse=True)
    if not registry:
        st.caption("No clients yet.")
    for rec in registry:
        label = f"{badge(rec)}  {rec.get('business_name') or rec['slug']}"
        st.button(label, key=f"nav_{rec['slug']}", width="stretch",
                  on_click=go, args=("client", rec["slug"]))
    missing_keys = check_keys()
    if missing_keys:
        st.error("Missing in .env: " + ", ".join(missing_keys))
    if not os.getenv("VOICEFLOW_API_KEY"):
        st.caption("No Voiceflow key: the website chat comes as a paste pack.")


# ---------------- view: new client ----------------

def view_new() -> None:
    st.header("New client")
    st.write("Paste the company's website and, if you've talked to them, your call notes. "
             "We read the site, pull out the facts, and fill in the intake from your notes.")
    st.info("Nothing is said to customers until you build an agent on **5 · Build**. Prices from your "
            "notes come in unapproved; you tick the ones the agent may quote.", icon="🛡️")

    with st.form("new_client"):
        url = st.text_input("Company website", placeholder="https://www.someplumbing.com", key="new_url")
        c1, c2 = st.columns(2)
        name = c1.text_input("Business name", key="new_name")
        employees = c2.text_input("Number of employees", key="new_employees")
        notes = st.text_area("Paste your call notes (optional)", height=300, key="new_notes",
                             placeholder="Messy is fine: discovery answers, onboarding answers, a transcript.")
        submitted = st.form_submit_button("Read website + notes", type="primary")
    if not submitted:
        return
    url = url.strip()
    if not re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+", url):
        st.error("That doesn't look like a website address.")
        return
    if "://" not in url:
        url = "https://" + url

    slug = clients.slug_for(url)
    clients.upsert(slug, website=url)
    cdir = cdir_for(slug)
    basics = {"business_name": name.strip(), "employee_count": employees.strip()}
    with st.status(f"Reading {url}", expanded=True) as status:
        try:
            run_step("1/3 Reading the website", crawl.run, url, cdir)
            clients.upsert(slug, status="crawled")
            run_step("2/3 Pulling out the business facts", extract.run, cdir)
            clients.upsert(slug, status="extracted")
            run_step("3/3 Reading your call notes" if notes.strip() else "3/3 Setting up the intake",
                     intake.run, cdir, notes, basics)
            clients.upsert(slug, status="intake")
        except StageError as e:
            status.update(label=f"Stopped: {e}", state="error")
            if e.log:
                st.code(e.log, language=None)
            return
        status.update(label="Website and notes read", state="complete", expanded=False)
    go("client", slug)
    st.rerun()


# ---------------- view: client ----------------

def overview(slug: str, rec: dict, profile: BusinessProfile | None) -> None:
    if profile is None:
        st.warning("The website hasn't been read yet. Start it from **New client**.")
        return
    policy = load(slug, "policy", FitPolicy)
    it = load(slug, "intake", Intake, Intake())
    pricing = load(slug, "pricing", PricingSheet, PricingSheet())
    answered = {}   # onboarding answers fill these facts even when the website didn't
    if policy and not policy.notes.startswith("DEMO"):
        answered = {"business_hours": bool(policy.regular_hours),
                    "service_area": bool(policy.service_zips or policy.service_cities),
                    "services_offered": bool(policy.services_offered)}
    found = [f for f in REQUIRED_PROFILE_FIELDS
             if getattr(profile, f).status != Status.missing or answered.get(f)]

    c1, c2, c3 = st.columns(3)
    risk = monthly_revenue_at_risk(it)
    with c1.container(border=True):
        if risk is None:
            st.metric("Missed jobs", "-")
            st.caption("Add missed calls a week and the average job on **1 · Call notes**.")
        else:
            st.metric("Missed jobs", f"~${risk:,.0f}/month")
            rate = it.booking_rate_pct if it.booking_rate_pct is not None else 100
            st.caption(f"{it.missed_calls_per_week:g} missed calls a week × {rate:g}% who'd book × "
                       f"${it.avg_job_value:,.0f} average job × 4.33 weeks")
    c2.metric("Required facts found", f"{len(found)} / {len(REQUIRED_PROFILE_FIELDS)}")
    done = sum(bool(rec.get(k)) for k in REVIEW_KEYS)
    c3.metric("Onboarding steps saved", f"{done} / {len(REVIEW_KEYS)}")

    gaps = [f"{FIELD_LABELS[f]} (not on the website)" for f in REQUIRED_PROFILE_FIELDS
            if f not in found and f != "business_hours"]
    if not (policy and policy.regular_hours.strip()) and not profile.business_hours.value:
        gaps.append("No business hours")
    if not (it.owner_phone.strip() or it.owner_email.strip()):
        gaps.append("No owner contact (phone or email)")
    if not it.notify.strip():
        gaps.append('No "who gets leads" (who is told about each new lead, and how)')
    if gaps:
        st.subheader("Gaps")
        for g in gaps:
            st.error(g)
    conflicts = [i for i in pricing.items if intake.CONFLICT_NOTE in i.notes]
    for i in conflicts:
        st.warning(f"Price **{i.service}** conflicts with what the owner won't quote "
                   f"(*{it.will_not_quote.strip()}*). Leave it unapproved unless the owner says otherwise.",
                   icon="🚫")
    for s in profile.staleness_signals:
        st.warning(s, icon="⚠️")

    st.subheader("Next step")
    steps = [("reviewed_intake", "1 · Call notes"), ("reviewed_facts", "2 · Business facts"),
             ("reviewed_policy", "3 · Who we serve"), ("reviewed_prices", "4 · Prices")]
    todo = [label for key, label in steps if not rec.get(key)]
    if rec.get("status") == "deployed" and rec.get("mode") == "live":
        st.write("Live agent built. Run the test calls on **5 · Build**.")
    elif todo:
        st.write("Check and save " + ", ".join(f"**{t}**" for t in todo) + " with the owner. "
                 "To show the owner something now, build a **Demo** on **5 · Build**.")
    else:
        st.write("Everything is saved. Build the **Live** agent on **5 · Build**.")


def tab_intake(slug: str) -> None:
    it = load(slug, "intake", Intake, Intake())
    st.caption("What you learned on the calls. Fix anything wrong, then **Save intake**.")
    with st.form(f"intake_{slug}"):
        st.markdown("**Owner**")
        c1, c2, c3 = st.columns(3)
        owner_name = c1.text_input("Owner name", it.owner_name)
        owner_phone = c2.text_input("Owner phone", it.owner_phone)
        owner_email = c3.text_input("Owner email", it.owner_email)
        st.markdown("**How calls are handled today**")
        c1, c2 = st.columns(2)
        who = c1.text_input("Who answers the phone today", it.who_answers_today)
        tool = c2.text_input("Scheduling tool", it.scheduling_tool)
        st.markdown("**Baseline numbers** (for the pitch and the monthly report)")
        c1, c2, c3, c4 = st.columns(4)
        missed = c1.number_input("Missed calls a week", min_value=0.0, step=1.0, value=it.missed_calls_per_week)
        rate = c2.number_input("% of callers who book", min_value=0.0, max_value=100.0, step=5.0,
                               value=it.booking_rate_pct)
        avg = c3.number_input("Average job ($)", min_value=0.0, step=50.0, value=it.avg_job_value)
        volume = c4.number_input("Calls a month", min_value=0.0, step=10.0, value=it.monthly_call_volume)
        st.markdown("**How the agent behaves**")
        will_not = st.text_area("Won't quote over the phone or chat", it.will_not_quote)
        booking = st.text_area("Booking rules", it.booking_rules)
        notify = st.text_input("Who gets each lead, and how", it.notify)
        voice = st.text_area("Brand voice", it.brand_voice)
        escalation = st.text_area("Escalation rules (one per line)", "\n".join(it.escalation_rules))
        extra = st.text_input("Extra lead fields (separate with ;)", "; ".join(it.lead_extra_fields))
        st.markdown("**FAQs** (no prices here: prices go on **4 · Prices**)")
        faqs = st.data_editor(
            pd.DataFrame([{"Question": f.question, "Answer": f.answer} for f in it.faqs],
                         columns=["Question", "Answer"], dtype=str),
            key=f"faqs_{slug}", num_rows="dynamic", hide_index=True, width="stretch",
            column_config={"Question": st.column_config.TextColumn(width="medium"),
                           "Answer": st.column_config.TextColumn(width="large")})
        notes = st.text_area("Other notes from the calls", it.notes)
        saved = st.form_submit_button("Save intake", type="primary")
    if not saved:
        return
    faq_list, errors = [], []
    for _, r in faqs.iterrows():
        q = r["Question"].strip() if isinstance(r["Question"], str) else ""
        a = r["Answer"].strip() if isinstance(r["Answer"], str) else ""
        if not q and not a:
            continue
        if not q or not a:
            errors.append(f"FAQ '{q or a}' needs both a question and an answer")
        elif intake.PRICE_RE.search(a):
            errors.append(f"FAQ '{q}' has a price in its answer; put prices on 4 · Prices so they need approval")
        else:
            faq_list.append(FAQ(question=q, answer=a))
    for e in errors:
        st.error(e)
    if errors:
        return
    clients.save_model(cdir_for(slug) / "intake.json", it.model_copy(update={
        "owner_name": owner_name.strip(), "owner_phone": owner_phone.strip(),
        "owner_email": owner_email.strip(), "who_answers_today": who.strip(),
        "scheduling_tool": tool.strip(), "missed_calls_per_week": missed, "booking_rate_pct": rate,
        "avg_job_value": avg, "monthly_call_volume": volume, "will_not_quote": will_not.strip(),
        "booking_rules": booking.strip(), "notify": notify.strip(), "brand_voice": voice.strip(),
        "escalation_rules": [e.strip() for e in escalation.splitlines() if e.strip()],
        "lead_extra_fields": split(extra), "faqs": faq_list, "notes": notes.strip()}))
    clients.upsert(slug, reviewed_intake=True)
    st.success("Saved.")


def tab_facts(slug: str, profile: BusinessProfile) -> None:
    st.caption("What the website says. Fix anything wrong, fill anything red, then **Save facts**. "
               "Separate list items with ;")
    rows = []
    for name, label in FIELD_LABELS.items():
        fact = getattr(profile, name)
        rows.append({"Field": label + (" *" if name in REQUIRED_PROFILE_FIELDS else ""),
                     "Value": fact_text(fact), "Status": STATUS_LABEL[fact.status.value],
                     "Source": fact.source_url or "", "_name": name})
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df, key=f"facts_{slug}", hide_index=True, width="stretch",
        column_order=["Field", "Value", "Status", "Source"],
        disabled=["Field", "Status", "Source"],
        column_config={"Value": st.column_config.TextColumn(width="large"),
                       "Source": st.column_config.LinkColumn(width="small", display_text="page")},
    )
    if st.button("Save facts", type="primary", key=f"save_facts_{slug}"):
        changed = 0
        for _, row in edited.iterrows():
            name = row["_name"]
            fact = getattr(profile, name)
            new = (row["Value"] or "").strip()
            if new == fact_text(fact):
                continue
            changed += 1
            value = split(new) if isinstance(fact, ListFact) else (new or None)
            setattr(profile, name, type(fact)(value=value, source_url=fact.source_url,
                                              status=Status.operator if new else Status.missing))
        clients.save_model(cdir_for(slug) / "profile.json", profile)
        clients.upsert(slug, reviewed_facts=True, business_name=profile.business_name.value)
        st.success(f"Saved ({changed} changed).")
        st.rerun()


def tab_policy(slug: str, profile: BusinessProfile) -> None:
    policy = load(slug, "policy", FitPolicy)
    if policy is None or policy.notes.startswith("DEMO"):
        start = demo.policy_from_profile(profile)
        start.callback_promise = "Someone from our team will call you back within one business hour."
        start.typical_lead_time = "usually next business day"
        start.notes = ""
        st.caption("Pre-filled from the website. Confirm each answer with the owner.")
    else:
        start = policy
    with st.form(f"policy_{slug}"):
        st.markdown("**Where they work**")
        zips = st.text_input("Service ZIP codes (comma-separated)", ", ".join(start.service_zips))
        cities = st.text_input("Service cities (separate with ;)", "; ".join(start.service_cities))
        st.markdown("**What they do**")
        offered = st.text_area("Services offered (separate with ;)", "; ".join(start.services_offered))
        not_offered = st.text_area("Services NOT offered (separate with ;)",
                                   "; ".join(start.services_not_offered))
        c1, c2, c3 = st.columns(3)
        residential = c1.checkbox("Serves homes", start.residential)
        commercial = c2.checkbox("Serves businesses", start.commercial)
        renters_ok = c3.checkbox("Takes jobs from renters", start.renters_ok)
        st.markdown("**When**")
        hours = st.text_input("Regular hours", start.regular_hours)
        c1, c2 = st.columns(2)
        emergency = c1.checkbox("Offers emergency service", start.emergency_service)
        emergency_hours = c2.text_input("Emergency hours (e.g. 24/7)", start.emergency_hours)
        lead = st.text_input("Typical wait for a visit", start.typical_lead_time)
        callback = st.text_input("Callback promise (said at the end of every call)", start.callback_promise)
        transfer = st.text_input("Owner's phone for emergencies (+14045551234)", start.owner_transfer_number)
        notes = st.text_area("Other notes for the agent", start.notes)
        saved = st.form_submit_button("Save who we serve", type="primary")
    if not saved:
        return
    zip_list = [z.strip() for z in zips.split(",") if z.strip()]
    bad = [z for z in zip_list if not re.fullmatch(r"\d{5}", z)]
    errors = []
    if bad:
        errors.append(f"Not 5-digit ZIPs: {', '.join(bad)}")
    if transfer.strip() and not re.fullmatch(r"\+[1-9]\d{7,14}", transfer.strip()):
        errors.append("Owner's phone must look like +14045551234")
    if not zip_list and not cities.strip():
        errors.append("Add at least one ZIP code or city")
    if not offered.strip():
        errors.append("Add at least one service offered")
    if not callback.strip():
        errors.append("Add a callback promise")
    if not hours.strip():
        errors.append("Add the regular hours")
    for e in errors:
        st.error(e)
    if errors:
        return
    clients.save_model(cdir_for(slug) / "policy.json", FitPolicy(
        service_zips=zip_list, service_cities=split(cities), services_offered=split(offered),
        services_not_offered=split(not_offered), residential=residential, commercial=commercial,
        renters_ok=renters_ok, regular_hours=hours.strip(), emergency_service=emergency,
        emergency_hours=emergency_hours.strip() if emergency else "", typical_lead_time=lead.strip(),
        callback_promise=callback.strip(), owner_transfer_number=transfer.strip(), notes=notes.strip(),
    ))
    clients.upsert(slug, reviewed_policy=True)
    st.success("Saved.")


def num(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) or x == "" else float(x)


def tab_prices(slug: str, profile: BusinessProfile) -> None:
    pricing = load(slug, "pricing", PricingSheet, PricingSheet())
    st.caption("Only rows with **Approved** ticked are ever said to a caller, always as an estimate. "
               "Add rows at the bottom of the table.")
    policy = load(slug, "policy", FitPolicy)
    from_demo = policy is None or policy.notes.startswith("DEMO")   # demos switch prices off
    share = st.toggle("Agent may share prices",
                      value=bool(pricing.items) if from_demo else pricing.share_prices,
                      key=f"share_{slug}")
    df = pd.DataFrame([{
        "Approved": i.approved, "Service": i.service, "Low $": i.low, "High $": i.high,
        "Unit": i.unit if i.unit in UNITS else "per job", "Notes": i.notes,
        "Source": "website" if i.source == "website" else "operator",
    } for i in pricing.items], columns=["Approved", "Service", "Low $", "High $", "Unit", "Notes", "Source"])
    df = df.astype({"Approved": bool, "Low $": float, "High $": float, "Service": str, "Unit": str,
                    "Notes": str, "Source": str})
    edited = st.data_editor(
        df, key=f"prices_{slug}", num_rows="dynamic", hide_index=True, width="stretch",
        disabled=["Source"],
        column_config={
            "Approved": st.column_config.CheckboxColumn(default=True),
            "Low $": st.column_config.NumberColumn(min_value=0, format="$%.0f"),
            "High $": st.column_config.NumberColumn(min_value=0, format="$%.0f"),
            "Unit": st.column_config.SelectboxColumn(options=UNITS, default="per job"),
            "Source": st.column_config.TextColumn(default="operator"),
        },
    )
    financing = st.text_input("Financing note for callers", pricing.financing_note or
                              profile.financing.value or "", key=f"fin_{slug}")
    st.caption(f"Every price is followed by: *{pricing.quote_rule}*")
    if st.button("Save prices", type="primary", key=f"save_prices_{slug}"):
        items, errors = [], []
        for _, r in edited.iterrows():
            service = (r["Service"] or "").strip() if isinstance(r["Service"], str) else ""
            low, high = num(r["Low $"]), num(r["High $"])
            if not service and low is None:
                continue
            if not service or (low is None and high is None):
                errors.append(f"Row '{service or '?'}' needs a service name and a price")
                continue
            items.append(PriceItem(service=service, low=low if low is not None else high,
                                   high=high if high is not None else low, unit=r["Unit"] or "per job",
                                   notes=r["Notes"] if isinstance(r["Notes"], str) else "",
                                   source="website" if r["Source"] == "website" else "operator",
                                   approved=bool(r["Approved"])))
        for e in errors:
            st.error(e)
        if errors:
            return
        clients.save_model(cdir_for(slug) / "pricing.json", pricing.model_copy(update={
            "items": items, "share_prices": share, "financing_note": financing.strip()}))
        clients.upsert(slug, reviewed_prices=True)
        approved = [i for i in items if i.approved] if share else []
        st.success(f"Saved. The agent may quote {len(approved)} price(s).")
        if approved:
            st.write("It will say, for example:")
            st.info(f"{prompt_builder.price_line(approved[0])[2:]}. {pricing.quote_rule}")


def build(slug: str, live: bool, chat_on: bool, phone_on: bool) -> None:
    """Render and deploy the chosen channels. Demo renders in memory and writes no policy/pricing."""
    cdir = cdir_for(slug)
    agent_dir = cdir / "agent"
    mode = "live" if live else "demo"
    built = set((clients.get_client(slug) or {}).get("channels") or [])
    deployed = False
    with st.status(f"Building the {mode} agent", expanded=True) as status:
        try:
            if live:
                out = {}
                call(lambda: out.update(inputs=prompt_builder.load_inputs(cdir)))
                profile, policy, pricing, it = out["inputs"]
            else:
                profile = load(slug, "profile", BusinessProfile)
                saved = load(slug, "intake", Intake, Intake())
                policy = demo.policy_from_profile(profile)
                pricing = PricingSheet(share_prices=False)
                it = Intake(business_name=saved.business_name)
            clients.upsert(slug, mode=mode)   # before deploying: demo agents get a [DEMO] name
            if phone_on:
                prompt, first = render(slug, profile, policy, pricing, it, channel="phone")
                (agent_dir / "prompt.md").write_text(prompt)
                (agent_dir / "first_message.txt").write_text(first + "\n")
                run_step("Phone: creating or updating the agent in ElevenLabs", deploy.deploy_text,
                         slug, prompt, first)
                built.add("phone")
                deployed = True
            if chat_on:
                prompt, first = render(slug, profile, policy, pricing, it, channel="chat")
                run_step("Website chat: writing the paste pack", voiceflow_deploy.export_pack,
                         cdir, prompt, first)
                if os.getenv("VOICEFLOW_API_KEY"):
                    run_step("Website chat: building it in Voiceflow", voiceflow_deploy.run, cdir, prompt, first)
                    deployed = True
                built.add("chat")
        except StageError as e:
            status.update(label=f"Stopped: {e}", state="error")
            if e.log:
                st.code(e.log, language=None)
            return
        status.update(label=f"{mode.title()} agent built", state="complete", expanded=False)
    vf_json = agent_dir / "voiceflow.json"
    project_id = json.loads(vf_json.read_text()).get("project_id") if vf_json.exists() else None
    clients.upsert(slug, channels=sorted(built), voiceflow_project_id=project_id,
                   status="deployed" if deployed else "prompted")


def show_built(slug: str) -> None:
    rec = clients.get_client(slug) or {}
    agent_dir = cdir_for(slug) / "agent"
    channels = rec.get("channels") or (["phone"] if rec.get("agent_id") else [])
    if "phone" in channels and rec.get("agent_id"):
        st.subheader("📞 Phone")
        st.markdown(f"**Agent:** `{rec['agent_id']}`  ({rec.get('mode') or '-'})")
        st.link_button("🎙️ Talk to the agent", rec.get("talk_url") or deploy.talk_url(rec["agent_id"]),
                       type="primary")
        if rec.get("dashboard_url"):
            st.markdown(f"[Open in ElevenLabs]({rec['dashboard_url']})")
        first_path, prompt_path = agent_dir / "first_message.txt", agent_dir / "prompt.md"
        if first_path.exists():
            st.markdown("**What the caller hears first**")
            st.info(first_path.read_text().strip())
        if prompt_path.exists():
            with st.expander("The phone agent's full instructions"):
                st.markdown(prompt_path.read_text())
    if "chat" in channels:
        st.subheader("💬 Website chat")
        snippet, preview = agent_dir / "voiceflow_snippet.html", agent_dir / "chat_preview.html"
        instructions, setup = agent_dir / "chat_instructions.md", agent_dir / "voiceflow_setup.md"
        if os.getenv("VOICEFLOW_API_KEY") and snippet.exists():
            st.markdown(f"Voiceflow project `{rec.get('voiceflow_project_id', '')}`. Paste this just before "
                        "`</body>` on every page of the client's site:")
            st.code(snippet.read_text().strip(), language="html")
            if preview.exists():
                st.markdown(f"**Chat preview:** open `{preview.resolve()}` in your browser, or")
                st.download_button("Download chat preview", preview.read_text(), file_name="chat_preview.html",
                                   mime="text/html", key=f"preview_{slug}")
        elif instructions.exists():
            st.warning("Voiceflow key not set: paste by hand.", icon="✋")
            if setup.exists():
                st.markdown(setup.read_text())
            st.markdown("**chat_instructions.md** (copy with the button in the corner)")
            st.code(instructions.read_text(), language=None)


def tab_build(slug: str) -> None:
    rec = clients.get_client(slug) or {}   # re-read: the tabs above may have just saved
    reviewed = all(rec.get(k) for k in REVIEW_KEYS)
    c1, c2 = st.columns(2)
    with c1:
        mode = st.radio("Mode", [DEMO_MODE, LIVE_MODE], key=f"mode_{slug}",
                        index=1 if reviewed and rec.get("mode") == "live" else 0)
        if not reviewed:
            st.caption("**Live** unlocks once **1 · Call notes**, **2 · Business facts**, "
                       "**3 · Who we serve** and **4 · Prices** are all saved.")
    with c2:
        st.markdown("**Channels**")
        chat_on = st.checkbox("Website chat (Voiceflow)", True, key=f"chat_{slug}")
        phone_on = st.checkbox("Phone (ElevenLabs)", False, key=f"phone_{slug}")
    live = mode == LIVE_MODE
    blocked = (live and not reviewed) or not (chat_on or phone_on)
    if st.button(f"Build {'live' if live else 'demo'} agent", type="primary", disabled=blocked,
                 key=f"build_{slug}"):
        build(slug, live, chat_on, phone_on)
    show_built(slug)
    test_calls(slug)


def test_calls(slug: str) -> None:
    cdir = cdir_for(slug)
    st.subheader("Test calls")
    st.caption("Call the agent with the link above and play each caller. Mark what happened.")
    tests_path = cdir / "tests.json"
    results = json.loads(tests_path.read_text()) if tests_path.exists() else {}
    changed = False
    for key, scenario, expect in TESTS:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"**{scenario}**  \n{expect}")
        value = c2.selectbox("Result", TEST_STATES, index=TEST_STATES.index(results.get(key, "Not tested")),
                             key=f"test_{slug}_{key}", label_visibility="collapsed")
        if value != results.get(key, "Not tested"):
            results[key], changed = value, True
    if changed:
        tests_path.write_text(json.dumps(results, indent=2))
    passed = sum(v == "Pass" for v in results.values())
    st.caption(f"{passed} of {len(TESTS)} passed")


def view_client(slug: str) -> None:
    rec = clients.get_client(slug)
    if not rec:
        st.error("Client not found.")
        return
    profile = load(slug, "profile", BusinessProfile)
    st.header(rec.get("business_name") or slug)
    meta = [badge(rec), (rec.get("vertical") or "").upper()]
    if rec.get("website"):
        meta.append(f"[{rec['website']}]({rec['website']})")
    st.markdown("  ·  ".join(m for m in meta if m))

    tabs = st.tabs(["Overview", "1 · Call notes", "2 · Business facts", "3 · Who we serve", "4 · Prices",
                    "5 · Build"])
    with tabs[0]:
        overview(slug, rec, profile)
    if profile is None:
        return
    with tabs[1]:
        tab_intake(slug)
    with tabs[2]:
        tab_facts(slug, profile)
    with tabs[3]:
        tab_policy(slug, profile)
    with tabs[4]:
        tab_prices(slug, profile)
    with tabs[5]:
        tab_build(slug)


if st.session_state.view == "client" and st.session_state.get("slug"):
    view_client(st.session_state.slug)
else:
    view_new()
