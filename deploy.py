"""Stage 5 - deploy: create or update this client's ElevenLabs agent.

run(cdir): read cdir/agent/prompt.md and first_message.txt, then deploy_text(slug, prompt, first_message).
deploy_text(slug, prompt, first_message):
  - Name from the registry record.
  - ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"]).
  - conversation_config = {"agent": {"first_message": ..., "language": "en",
        "prompt": {"prompt": ..., "llm": <a fast model from ElevenLabs' supported list>}},
        "tts": {"voice_id": os.environ["ELEVENLABS_VOICE_ID"]}}
  - If cdir/agent/agent.json has agent_id: client.conversational_ai.agents.update(agent_id=..., ...).
    Else: client.conversational_ai.agents.create(name="<Business name> - Receptionist", ...) and
    save {"agent_id": ...} to agent.json.
  - clients.upsert(slug, agent_id=...). Print the agent's dashboard link for a browser test call.
"""
import json
import os
import sys
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from rich.console import Console
from rich.markup import escape

import clients

LLM = "gemini-3.5-flash-lite"
REASONING_EFFORT = "minimal"
console = Console(highlight=False, soft_wrap=True)


def fail(message: str) -> None:
    console.print(f"[red]deploy failed:[/red] {escape(message)}")
    sys.exit(1)


def run(cdir: Path) -> None:
    agent_dir = cdir / "agent"
    prompt_path = agent_dir / "prompt.md"
    first_path = agent_dir / "first_message.txt"
    for path in (prompt_path, first_path):
        if not path.exists():
            fail(f"{path} not found; run the prompt stage first.")
    deploy_text(cdir.name, prompt_path.read_text(), first_path.read_text().strip())


def deploy_text(slug: str, prompt: str, first_message: str) -> None:
    """Create or update the client's ElevenLabs agent with this prompt and opening line."""
    agent_json = clients.client_dir(slug) / "agent" / "agent.json"
    for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
        if not os.getenv(name):
            fail(f"{name} is not set in .env")

    rec = clients.get_client(slug) or {}
    business_name = rec.get("business_name") or slug
    conversation_config = {
        "agent": {
            "first_message": first_message,
            "language": "en",
            "prompt": {
                "prompt": prompt,
                "llm": LLM,
                "reasoning_effort": REASONING_EFFORT,
            },
        },
        "tts": {"voice_id": os.environ["ELEVENLABS_VOICE_ID"]},
    }
    demo = rec.get("mode") == "demo"
    name = f"{'[DEMO] ' if demo else ''}{business_name} - Receptionist"

    existing = json.loads(agent_json.read_text()).get("agent_id") if agent_json.exists() else None
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    try:
        if existing:
            client.conversational_ai.agents.update(
                agent_id=existing, name=name, conversation_config=conversation_config
            )
            agent_id = existing
            console.print(f"Updated agent {agent_id} ({name}, llm {LLM})")
        else:
            agent_id = client.conversational_ai.agents.create(
                name=name, conversation_config=conversation_config
            ).agent_id
            agent_json.write_text(json.dumps({"agent_id": agent_id}, indent=2))
            console.print(f"Created agent {agent_id} ({name}, llm {LLM})")
    except ApiError as e:
        fail(f"ElevenLabs HTTP {e.status_code}: {e.body}")

    link = talk_url(agent_id)
    clients.upsert(slug, agent_id=agent_id, talk_url=link,
                   dashboard_url=f"https://elevenlabs.io/app/agents/agents/{agent_id}")
    console.print(f"Share this link to talk to the agent: {link}")
    console.print(f"Edit it in ElevenLabs: https://elevenlabs.io/app/agents/agents/{agent_id}")


def talk_url(agent_id: str) -> str:
    """Public page where anyone with the link can talk to the agent in their browser."""
    return f"https://elevenlabs.io/app/talk-to?agent_id={agent_id}"
