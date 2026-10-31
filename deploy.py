"""Stage 5 - deploy: create or update this client's ElevenLabs agent.

run(cdir):
  - Read cdir/agent/prompt.md and first_message.txt (and the registry record for the name).
  - ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"]).
  - conversation_config = {"agent": {"first_message": ..., "language": "en",
        "prompt": {"prompt": ..., "llm": <a fast model from ElevenLabs' supported list>}},
        "tts": {"voice_id": os.environ["ELEVENLABS_VOICE_ID"]}}
  - If cdir/agent/agent.json has agent_id: client.conversational_ai.agents.update(agent_id=..., ...).
    Else: client.conversational_ai.agents.create(name="<Business name> - Receptionist", ...) and
    save {"agent_id": ...} to agent.json.
  - clients.upsert(slug, agent_id=...). Print the agent's dashboard link for a browser test call.
"""
from pathlib import Path


def run(cdir: Path) -> None:
    raise NotImplementedError("deploy: see CURSOR_PROMPTS.md, Prompt 1")
