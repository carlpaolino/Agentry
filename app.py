"""Frontdesk Builder: the operator dashboard.

    streamlit run app.py

Two modes:
  Demo     (cold calls)  website -> agent + talk-to link in a few minutes. No review, no prices.
  Onboard  (after a sale) review facts, who we serve and prices, then deploy the live agent.
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
import prompt_builder
from runner import StageError, call
from schema import (REQUIRED_PROFILE_FIELDS, BusinessProfile, FitPolicy, ListFact, PriceItem,
                    PricingSheet, Status)

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
    st.button("➕ New demo", width="stretch", type="primary", on_click=go, args=("new",))
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


# ---------------- view: new demo ----------------

def view_new() -> None:
    st.header("Build a demo from a website")
    st.write("Paste the company's website. In a few minutes you get a link the owner can open "
             "and talk to **their own** AI receptionist.")
    st.info("Demo agents use only what's on the website, **never quote prices**, and tell callers "
            "the team will call back. After a sale, open the client and complete onboarding.", icon="🛡️")

    with st.form("new_demo"):
        url = st.text_input("Company website", placeholder="https://www.someplumbing.com")
        submitted = st.form_submit_button("Build demo", type="primary")
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
    with st.status(f"Building demo for {url}", expanded=True) as status:
        try:
            run_step("1/4 Reading the website", crawl.run, url, cdir)
            clients.upsert(slug, status="crawled")
            run_step("2/4 Pulling out the business facts", extract.run, cdir)
            clients.upsert(slug, status="extracted")
            run_step("3/4 Setting safe demo rules", demo.prepare, cdir)
            clients.upsert(slug, status="reviewed")
            run_step("4/4 Writing the agent and creating it in ElevenLabs",
                     lambda d: (prompt_builder.run(d), deploy.run(d)), cdir)
            clients.upsert(slug, status="deployed")
        except StageError as e:
            status.update(label=f"Stopped: {e}", state="error")
            if e.log:
                st.code(e.log, language=None)
            return
        status.update(label="Demo ready", state="complete", expanded=False)

    rec = clients.get_client(slug) or {}
    st.success(f"Demo ready for **{rec.get('business_name') or slug}**")
    st.link_button("🎙️ Talk to the demo agent", rec.get("talk_url", ""), type="primary")
    st.code(rec.get("talk_url", ""), language=None)
    st.caption("Send this link to the owner, or open it on the call and let them listen.")
    st.button("Open client", on_click=go, args=("client", slug))


# ---------------- view: client ----------------

def overview(slug: str, rec: dict, profile: BusinessProfile | None) -> None:
    if profile is None:
        st.warning("The website hasn't been read yet. Build a demo first.")
        return
    policy = load(slug, "policy", FitPolicy)
    answered = {}   # onboarding answers fill these facts even when the website didn't
    if policy and not policy.notes.startswith("DEMO"):
        answered = {"business_hours": bool(policy.regular_hours),
                    "service_area": bool(policy.service_zips or policy.service_cities),
                    "services_offered": bool(policy.services_offered)}
    found = [f for f in REQUIRED_PROFILE_FIELDS
             if getattr(profile, f).status != Status.missing or answered.get(f)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Required facts found", f"{len(found)} / {len(REQUIRED_PROFILE_FIELDS)}")
    c2.metric("Mode", "Demo" if rec.get("mode") == "demo" else "Live" if rec.get("mode") == "live" else "-")
    done = sum(bool(rec.get(k)) for k in ("reviewed_facts", "reviewed_policy", "reviewed_prices"))
    c3.metric("Onboarding steps saved", f"{done} / 3")

    missing = [FIELD_LABELS[f] for f in REQUIRED_PROFILE_FIELDS if f not in found]
    if missing:
        st.error("Missing from the website: " + ", ".join(missing))
    for s in profile.staleness_signals:
        st.warning(s, icon="⚠️")

    st.subheader("Next step")
    if rec.get("mode") == "demo":
        st.write("This is a **demo**. Once the owner says yes, go through **Business facts → "
                 "Who we serve → Prices** with them, then **Agent → Deploy live agent**.")
    elif rec.get("mode") == "live":
        st.write("Live agent deployed. Run the test calls on the **Agent** tab.")
    else:
        st.write("Build a demo, or complete onboarding and deploy.")


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


def tab_agent(slug: str) -> None:
    cdir = cdir_for(slug)
    rec = clients.get_client(slug) or {}   # re-read: the tabs above may have just saved
    reviewed = all(rec.get(k) for k in ("reviewed_facts", "reviewed_policy", "reviewed_prices"))
    c1, c2 = st.columns([2, 1])
    with c1:
        if rec.get("agent_id"):
            st.markdown(f"**Agent:** `{rec['agent_id']}`  ({'demo' if rec.get('mode') == 'demo' else 'live'})")
            st.link_button("🎙️ Talk to the agent", rec.get("talk_url") or deploy.talk_url(rec["agent_id"]),
                           type="primary")
            if rec.get("dashboard_url"):
                st.markdown(f"[Open in ElevenLabs]({rec['dashboard_url']})")
        else:
            st.write("No agent yet.")
    with c2:
        if not reviewed:
            st.caption("Save **Business facts**, **Who we serve** and **Prices** to unlock the live agent.")
        if st.button("Deploy live agent", type="primary", disabled=not reviewed, key=f"live_{slug}"):
            clients.upsert(slug, mode="live")
            with st.status("Deploying the live agent", expanded=True) as status:
                try:
                    run_step("Writing the agent's instructions", prompt_builder.run, cdir)
                    clients.upsert(slug, status="prompted")
                    run_step("Updating the agent in ElevenLabs", deploy.run, cdir)
                    clients.upsert(slug, status="deployed")
                except StageError as e:
                    status.update(label=f"Stopped: {e}", state="error")
                    if e.log:
                        st.code(e.log, language=None)
                    return
                status.update(label="Live agent deployed", state="complete")
            st.rerun()

    prompt_path, first_path = cdir / "agent" / "prompt.md", cdir / "agent" / "first_message.txt"
    if first_path.exists():
        st.markdown("**What the caller hears first**")
        st.info(first_path.read_text().strip())
    if prompt_path.exists():
        with st.expander("The agent's full instructions"):
            st.markdown(prompt_path.read_text())

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

    tabs = st.tabs(["Overview", "1 · Business facts", "2 · Who we serve", "3 · Prices", "4 · Agent"])
    with tabs[0]:
        overview(slug, rec, profile)
    if profile is None:
        return
    with tabs[1]:
        tab_facts(slug, profile)
    with tabs[2]:
        tab_policy(slug, profile)
    with tabs[3]:
        tab_prices(slug, profile)
    with tabs[4]:
        tab_agent(slug)


if st.session_state.view == "client" and st.session_state.get("slug"):
    view_client(st.session_state.slug)
else:
    view_new()
