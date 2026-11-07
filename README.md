# Frontdesk Builder: AI receptionists for home-service businesses

## Start the dashboard (Mac)
Double-click `start.command` (first run installs everything), or:

    source .venv/bin/activate && pip install -r requirements.txt && streamlit run app.py

It opens in your browser at http://localhost:8501. Needs `.env` with ANTHROPIC_API_KEY,
FIRECRAWL_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID (see `.env.example`).

## Two modes
**Demo (cold calls):** New demo → paste the website → Build demo. In a few minutes you get a
"Talk to the demo agent" link to send the owner. Demo agents use only what's on the website,
never quote prices, and say the team will call back. Named "[DEMO] ..." in ElevenLabs.

**Onboard (after a sale):** open the client and go through, with the owner:
1. Business facts: fix anything wrong, fill anything red.
2. Who we serve: ZIPs, cities, services, homes/businesses, hours, emergencies, callback promise.
3. Prices: tick Approved only on prices the owner OKs.
4. Agent: Deploy live agent (unlocks once 1–3 are saved), then run the 8 test calls.
The same ElevenLabs agent is updated, so the demo link becomes the live agent.

## Command line (same pipeline)
    python build_agent.py https://somehvac.com --demo
    python build_agent.py https://somehvac.com                   # full onboarding in the terminal
    python build_agent.py --client somehvac --from-stage prompt
    python build_agent.py --list

Each client lives in `clients/<slug>/`; `clients/registry.json` lists them all.
