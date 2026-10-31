# Voice Agents for Plumbing and HVAC

Company URL in, ElevenLabs receptionist agent out, one folder per client.

    python build_agent.py https://somehvac.com
    python build_agent.py --client somehvac --from-stage prompt
    python build_agent.py --list

Setup: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`, then fill `.env` from `.env.example`.

Build it with Cursor: follow CURSOR_PROMPTS.md, one prompt at a time.
