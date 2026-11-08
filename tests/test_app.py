"""The dashboard end to end with Streamlit's AppTest, on a COPY of clients/.

Firecrawl, Claude, ElevenLabs and Voiceflow are fakes; the stage code (crawl, extract, intake,
prompt_builder, deploy, voiceflow_deploy) runs for real against them.
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import clients
import crawl
import deploy
import extract
import intake
import voiceflow_deploy
from schema import BusinessProfile
from tests.test_voiceflow import FakeVoiceflow

ROOT = Path(__file__).resolve().parent.parent
URL = "https://newco-test.com"
SLUG = "newco-test"
NOTES = """call w/ dana (owner) tues
- ~10 missed calls a week, maybe 5 of 10 book. avg ticket 300
- drain cleaning 150-250. won't quote water heater replacements over the phone, tech has to see it
- zips 30301 30302 only
- leads -> text dana
"""


def fake_profile() -> dict:
    p = BusinessProfile().model_dump(mode="json")
    found = lambda v: {"value": v, "source_url": URL, "status": "found"}
    p.update(business_name=found("NewCo Plumbing"), vertical=found("plumbing"),
             main_phone=found("(404) 555-0100"), service_area=found(["Atlanta, GA", "Marietta, GA"]),
             business_hours=found("Mon-Fri 8am-5pm"), services_offered=found(["Drain cleaning", "Water heaters"]))
    return p


def fake_draft() -> "intake._Draft":
    return intake._Draft(
        business_name="", employee_count="", owner_name="Dana", owner_phone="", owner_email="",
        who_answers_today="Dana's cell", scheduling_tool="", missed_calls_per_week=10, booking_rate_pct=50,
        avg_job_value=300, monthly_call_volume=None,
        will_not_quote="Water heater replacements over the phone; a tech has to see it.",
        booking_rules="", faqs=[intake._FAQ(question="Do you do drains?", answer="Yes, drain cleaning.")],
        lead_extra_fields=[], notify="Text Dana", escalation_rules=[], brand_voice="", notes="",
        service_zips=["30301", "30302"], service_cities=[], services_offered=["Drain cleaning"],
        services_not_offered=[], residential=True, commercial=False, renters_ok=None,
        regular_hours="Mon-Fri 8am-5pm", emergency_service=False, emergency_hours="", typical_lead_time="",
        price_items=[intake._Price(service="Drain cleaning", low=150, high=250, unit="per job", notes="")])


class FakeClaude:
    def __init__(self, api_key=None):
        self.messages = self

    def parse(self, output_format=None, **_):
        if output_format is crawl.PagePick:
            out = crawl.PagePick(urls=[f"{URL}/contact"])
        elif output_format is extract._Extraction:
            out = extract._Extraction.model_validate({"profile": fake_profile(), "price_items": [
                {"service": "Water heater installation", "low": 1200, "high": 2500, "unit": "per job",
                 "notes": "", "source_url": URL}]})
        elif output_format is intake._Draft:
            out = fake_draft()
        else:
            raise AssertionError(f"unexpected Claude call for {output_format}")
        return SimpleNamespace(parsed_output=out, stop_reason="end_turn")


class FakeFirecrawl:
    def __init__(self, api_key=None):
        pass

    def map(self, url):
        return SimpleNamespace(links=[SimpleNamespace(url=f"{URL}/contact", title="Contact")])

    def scrape(self, page, **_):
        return SimpleNamespace(markdown=f"# NewCo Plumbing\nPage {page}. Call (404) 555-0100.")


class FakeElevenLabs:
    calls = []

    def __init__(self, api_key=None):
        self.conversational_ai = SimpleNamespace(agents=self)

    def create(self, **kw):
        FakeElevenLabs.calls.append(("create", kw))
        return SimpleNamespace(agent_id="agent_fake123")

    def update(self, **kw):
        FakeElevenLabs.calls.append(("update", kw))


@pytest.fixture
def env(tmp_path, monkeypatch):
    real_registry = (ROOT / "clients" / "registry.json").read_bytes()
    shutil.copytree(ROOT / "clients", tmp_path / "clients")
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(clients, "REGISTRY", tmp_path / "clients" / "registry.json")
    for name in ("ANTHROPIC_API_KEY", "FIRECRAWL_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.setenv(name, "test-key")      # set first, so the app's load_dotenv keeps them
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "test-voice")
    monkeypatch.setenv("VOICEFLOW_API_KEY", "")
    monkeypatch.setenv("VOICEFLOW_WORKSPACE_ID", "ws1")
    for module in (crawl, extract, intake):
        monkeypatch.setattr(module.anthropic, "Anthropic", FakeClaude)
    monkeypatch.setattr(crawl, "Firecrawl", FakeFirecrawl)
    monkeypatch.setattr(deploy, "ElevenLabs", FakeElevenLabs)
    FakeElevenLabs.calls = []
    yield tmp_path / "clients"
    assert (ROOT / "clients" / "registry.json").read_bytes() == real_registry, "real clients/ was touched"


def new_client(at: AppTest) -> None:
    at.run()
    at.text_input(key="new_url").input(URL)
    at.text_input(key="new_name").input("NewCo Plumbing")
    at.text_input(key="new_employees").input("6")
    at.text_area(key="new_notes").input(NOTES)
    next(b for b in at.button if b.label == "Read website + notes").click()
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == "client" and at.session_state["slug"] == SLUG


def texts(at: AppTest) -> str:
    parts = [e.value for kind in (at.markdown, at.warning, at.error, at.info, at.success, at.caption, at.code)
             for e in kind]
    return "\n".join(str(p) for p in parts)


def click(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click()
    at.run()
    assert not at.exception, at.exception


def test_notes_to_demo_chat_pack_to_live_phone(env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    new_client(at)
    cdir = env / SLUG
    rec = json.loads((env / "registry.json").read_text())[SLUG]
    assert rec["status"] == "intake" and rec["employee_count"] == "6"

    # Overview: ROI card, gaps, won't-quote conflict
    assert any(m.value == "~$6,495/month" for m in at.metric)       # 10 x 50% x $300 x 4.33
    page = texts(at)
    assert "No owner contact" in page
    assert "Water heater installation" in page and "conflicts with what the owner won't quote" in page

    # Demo, chat only, no Voiceflow key: paste pack, and policy/pricing untouched
    before = {n: (cdir / n).read_bytes() for n in ("policy.json", "pricing.json")}
    click(at, "Build demo agent")
    page = texts(at)
    assert "Voiceflow key not set: paste by hand." in page
    assert "Start every new chat with:" in page
    assert {n: (cdir / n).read_bytes() for n in before} == before
    assert (cdir / "agent" / "chat_instructions.md").exists()
    assert FakeElevenLabs.calls == []

    # Live is blocked until all four tabs are saved
    at.radio(key=f"mode_{SLUG}").set_value("Live (reviewed)")
    at.run()
    assert at.button(key=f"build_{SLUG}").disabled
    for label in ("Save intake", "Save facts", "Save who we serve", "Save prices"):
        click(at, label)
    rec = json.loads((env / "registry.json").read_text())[SLUG]
    assert all(rec.get(k) for k in ("reviewed_intake", "reviewed_facts", "reviewed_policy", "reviewed_prices"))

    # Live, chat + phone
    at.radio(key=f"mode_{SLUG}").set_value("Live (reviewed)")
    at.checkbox(key=f"phone_{SLUG}").check()
    at.run()
    assert not at.button(key=f"build_{SLUG}").disabled
    at.button(key=f"build_{SLUG}").click()
    at.run()
    assert not at.exception, at.exception
    assert [c[0] for c in FakeElevenLabs.calls] == ["create"]
    assert FakeElevenLabs.calls[0][1]["name"] == "NewCo Plumbing - Receptionist"
    rec = json.loads((env / "registry.json").read_text())[SLUG]
    assert rec["mode"] == "live" and rec["status"] == "deployed" and rec["agent_id"] == "agent_fake123"
    assert rec["channels"] == ["chat", "phone"]
    prompt = (cdir / "agent" / "prompt.md").read_text()
    assert "30301" in prompt and "Marietta" not in prompt              # notes-only service area
    assert "Voiceflow key not set: paste by hand." in texts(at)


def test_chat_with_voiceflow_key_shows_snippet(env, monkeypatch):
    monkeypatch.setenv("VOICEFLOW_API_KEY", "vfp_test_secret_token")
    fake = FakeVoiceflow()
    real_client = voiceflow_deploy.client
    monkeypatch.setattr(voiceflow_deploy, "client", lambda transport=None: real_client(httpx.MockTransport(fake)))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    new_client(at)
    click(at, "Build demo agent")

    assert "publish" in fake.names()
    assert any("cdn.voiceflow.com" in c.value for c in at.code)
    rec = json.loads((env / "registry.json").read_text())[SLUG]
    assert rec["voiceflow_project_id"] == "proj123" and rec["channels"] == ["chat"]
    assert rec["mode"] == "demo" and rec["status"] == "deployed"
